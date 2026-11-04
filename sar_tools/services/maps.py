"""Bounded QGIS task queue for loading external maps without blocking the dock."""

import time

from qgis.core import (
    QgsApplication,
    QgsBlockingNetworkRequest,
    QgsDataSourceUri,
    QgsFeedback,
    QgsLayerTreeLayer,
    QgsRasterLayer,
    QgsTask,
)
from qgis.PyQt.QtCore import QCoreApplication, QObject, QUrl, pyqtSignal
from qgis.PyQt.QtNetwork import QNetworkRequest

from ..core.catalog import capabilities_url, wms_parameters, wmts_parameters
from ..core.errors import SarError
from .operation import ensure_groups, operation_path


class MapTask(QgsTask):
    def __init__(self, source, done, diagnostics):
        super().__init__("SAR: " + source["name"], QgsTask.Flag.CanCancel)
        self.source = source
        self.done = done
        self.diagnostics = diagnostics
        self.feedback = QgsFeedback()
        self.layer = None
        self.failure = None
        self.started = time.monotonic()

    def cancel(self):
        self.feedback.cancel()
        super().cancel()

    def run(self):
        try:
            if self.isCanceled():
                return False
            if self.source["type"] == "xyz":
                params = {
                    "type": "xyz",
                    "url": self.source["url"],
                    "zmin": str(self.source["zmin"]),
                    "zmax": str(self.source["zmax"]),
                    "http-header:user-agent": "QGIS-SAR-Tools/0.1 (QGIS desktop plugin)",
                }
            else:
                request = QNetworkRequest(QUrl(capabilities_url(self.source)))
                request.setTransferTimeout(20000)
                network = QgsBlockingNetworkRequest()
                error = network.get(request, False, self.feedback)
                if self.isCanceled():
                    return False
                if error != QgsBlockingNetworkRequest.ErrorCode.NoError:
                    raise SarError(
                        "MAP_NETWORK",
                        "Nie można połączyć się ze źródłem mapy. Spróbuj ponownie później.",
                    )
                payload = bytes(network.reply().content())
                params = (wmts_parameters if self.source["type"] == "wmts" else wms_parameters)(
                    self.source, payload
                )
            self.setProgress(50)
            uri = QgsDataSourceUri()
            for key, value in params.items():
                # Each WMS layer/style is a separate URI parameter for QGIS.
                if self.source["type"] == "wms" and key in ("layers", "styles"):
                    for item in value.split(","):
                        uri.setParam(key, item)
                else:
                    uri.setParam(key, value)
            layer = QgsRasterLayer(bytes(uri.encodedUri()).decode(), self.source["name"], "wms")
            if not layer.isValid():
                raise SarError(
                    "MAP_PROVIDER",
                    "QGIS nie mógł otworzyć tej mapy. Sprawdź połączenie i dostępność źródła.",
                )
            layer.setCustomProperty("sar/source", self.source["id"])
            layer.setAttribution(self.source["attribution"])
            layer.setAttributionUrl(
                self.source.get("attribution_url", self.source["documentation"])
            )
            layer.renderer().setOpacity(self.source["opacity"])
            layer.moveToThread(QCoreApplication.instance().thread())
            self.layer = layer
            self.setProgress(100)
            return not self.isCanceled()
        except SarError as exc:
            self.failure = (exc.code, str(exc))
            return False
        except Exception:
            self.diagnostics.exception("MAP_INTERNAL")
            self.failure = (
                "MAP_INTERNAL",
                "Nie udało się dodać mapy. Szczegóły zapisano w diagnostyce.",
            )
            return False

    def finished(self, success):
        self.diagnostics.event(
            "map_task %s %.2fs %s"
            % (self.source["id"], time.monotonic() - self.started, "ok" if success else "stopped")
        )
        self.done(self, success)


class MapQueue(QObject):
    status = pyqtSignal(str, str)
    progress = pyqtSignal(int, int)
    settled = pyqtSignal()

    def __init__(self, project, diagnostics, parent=None):
        super().__init__(parent)
        self.project = project
        self.diagnostics = diagnostics
        self.pending = []
        self.active = {}
        self.retired = {}
        self.generation = 0
        self.total = 0
        self.completed = 0
        self.closed = False

    def add(self, sources):
        operation_path(self.project)
        loaded = {
            layer.customProperty("sar/source", "") for layer in self.project.mapLayers().values()
        }
        queued = {s["id"] for s in self.pending} | set(self.active)
        if not self.active and not self.pending:
            self.total = self.completed = 0
        for source in sources:
            if source["id"] not in loaded and source["id"] not in queued:
                self.pending.append(source)
                queued.add(source["id"])
                self.total += 1
                self.status.emit(source["id"], "W kolejce")
        self._pump()

    def cancel(self):
        self.generation += 1
        for source in self.pending:
            self.status.emit(source["id"], "Anulowano")
        self.pending.clear()
        for task in list(self.active.values()):
            task.cancel()
            self.status.emit(task.source["id"], "Anulowano")
            self.retired[id(task)] = task
        self.active.clear()
        self.total = self.completed = 0
        self.progress.emit(0, 0)

    def close(self):
        self.closed = True
        self.cancel()

    def _pump(self):
        if self.closed:
            return
        while self.pending and len(self.active) + len(self.retired) < 2:
            source = self.pending.pop(0)
            generation = self.generation

            def done(task, success, expected=generation):
                self._done(task, success, expected)

            task = MapTask(source, done, self.diagnostics)
            self.active[source["id"]] = task
            self.status.emit(source["id"], "Ładowanie…")
            QgsApplication.taskManager().addTask(task)
        self.progress.emit(self.completed, self.total)

    def _done(self, task, success, generation):
        if self.closed or generation != self.generation:
            self.retired.pop(id(task), None)
            task.layer = None
            self._pump()
            return
        source = task.source
        self.active.pop(source["id"], None)
        try:
            if success and task.layer is not None:
                operation_path(self.project)
                existing = {
                    layer.customProperty("sar/source", "")
                    for layer in self.project.mapLayers().values()
                }
                if source["id"] not in existing:
                    group = ensure_groups(self.project)[source["group"]]
                    self.project.addMapLayer(task.layer, False)
                    node = QgsLayerTreeLayer(task.layer)
                    node.setItemVisibilityChecked(False)
                    group.addChildNode(node)
                    node.setItemVisibilityChecked(source["default_visible"])
                self.status.emit(source["id"], "Dodano")
            else:
                code, message = task.failure or ("MAP_CANCELLED", "Anulowano")
                self.status.emit(source["id"], message + " [" + code + "]")
        except Exception:
            self.diagnostics.exception("MAP_ATTACH")
            self.status.emit(source["id"], "Nie udało się dołączyć mapy [MAP_ATTACH]")
        finally:
            task.layer = None
            self.completed += 1
            self._pump()
            if not self.pending and not self.active:
                self.settled.emit()
