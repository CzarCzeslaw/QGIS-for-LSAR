"""Plugin lifecycle and action boundary. Heavy/network work lives in services."""

import functools
import logging
from pathlib import Path
from urllib.parse import urlencode

from qgis.core import (
    Qgis,
    QgsApplication,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsPointXY,
    QgsProject,
    QgsProviderRegistry,
    QgsRasterLayer,
    QgsSettings,
)
from qgis.PyQt.QtCore import QStandardPaths, Qt, QUrl
from qgis.PyQt.QtGui import QAction, QDesktopServices, QIcon
from qgis.PyQt.QtWidgets import QDialog, QFileDialog, QInputDialog, QLabel

from .core.catalog import load_catalog
from .core.diagnostics import Diagnostics
from .core.errors import SarError
from .services.location import LocationService
from .services.maps import MapQueue
from .services.network import AddressSearch
from .services.operation import create_operation, ensure_groups, operation_path, restore_layers
from .ui.dock import SarDock
from .ui.lkp_dialog import LkpDialog


class SarToolsPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.project = QgsProject.instance()
        self.settings = QgsSettings()
        self.dock = None
        self.action = None
        self.closed = False
        self.connections = []
        self.results = []
        self.sources = load_catalog()
        log_root = (
            Path(
                QStandardPaths.writableLocation(
                    QStandardPaths.StandardLocation.AppLocalDataLocation
                )
            )
            / "sar_tools"
            / "logs"
        )
        self.diagnostics = Diagnostics(log_root)
        self.locations = LocationService(iface.mapCanvas(), self.project)
        self.search = AddressSearch(self.diagnostics)
        self.maps = MapQueue(self.project, self.diagnostics)

    def connect(self, signal, function, guarded=True):
        slot = self.guard(function) if guarded else function
        signal.connect(slot)
        self.connections.append((signal, slot))

    def guard(self, function):
        @functools.wraps(function)
        def action(*args, **kwargs):
            if self.closed:
                return None
            try:
                return function(*args, **kwargs)
            except SarError as exc:
                self.diagnostics.event("action_failed", exc.code)
                self.notify(str(exc), exc.code)
            except Exception:
                self.diagnostics.exception("UNEXPECTED")
                self.notify(
                    "Operacja nie powiodła się. Szczegóły zapisano w diagnostyce.", "UNEXPECTED"
                )
            return None

        return action

    def initGui(self):
        self.dock = SarDock(self.sources, self.iface.mainWindow())
        self.iface.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.dock)
        self.dock.hide()
        self.action = QAction(
            QIcon(str(Path(__file__).parent / "icon.svg")), "SAR Tools", self.iface.mainWindow()
        )
        self.connect(self.action.triggered, self.show)
        self.iface.addToolBarIcon(self.action)
        self.iface.addPluginToMenu("SAR Tools", self.action)
        bindings = (
            (self.dock.create_requested, self.create),
            (self.dock.open_requested, self.open),
            (self.dock.save_requested, self.save),
            (self.dock.restore_requested, self.restore),
            (self.dock.maps_requested, self.load_maps),
            (self.dock.cancel_maps_requested, self.maps.cancel),
            (self.dock.visibility_requested, self.visibility),
            (self.dock.opacity_requested, self.opacity),
            (self.dock.search_requested, self.search_address),
            (self.dock.cancel_search_requested, self.search.cancel),
            (self.dock.locate_requested, self.locate),
            (self.dock.lkp_requested, self.save_lkp),
            (self.dock.dem_requested, self.add_dem),
            (self.dock.profile_requested, self.profile),
            (self.dock.link_requested, self.open_link),
            (self.dock.diagnostic_requested, self.export_diagnostics),
            (self.dock.health_requested, self.show_health),
            (self.dock.developer_changed, self.set_developer),
            (self.search.results, self.got_results),
            (self.search.failed, self.search_failed),
            (self.search.busy, self.dock.search_busy),
            (self.maps.status, self.dock.map_status),
            (self.maps.progress, self.dock.progress),
            (self.maps.settled, self.maps_settled),
            (self.project.cleared, self.project_cleared),
            (self.project.readProject, self.project_loaded),
            (self.project.layersAdded, self.sync),
            (self.project.layersRemoved, self.sync),
            (self.project.layerTreeRoot().visibilityChanged, self.sync),
            (self.iface.mapCanvas().renderComplete, self.sync),
        )
        for signal, function in bindings:
            self.connect(signal, function)
        self.attribution = QLabel(self.iface.mapCanvas())
        self.attribution.setObjectName("SarMapAttribution")
        self.attribution.setTextFormat(Qt.TextFormat.PlainText)
        self.attribution.setStyleSheet(
            "background: rgba(255,255,255,225); color: #202020; padding: 3px;"
        )
        self.attribution.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.attribution.move(8, 8)
        self.dock.folder_edit.setText(self.settings.value("sar_tools/parent_folder", "", type=str))
        self.dock.developer.setChecked(self.settings.value("sar_tools/developer", False, type=bool))
        self.project_loaded()
        self.show_health()
        self.diagnostics.event("plugin_loaded")

    def show(self, *_):
        self.dock.show()
        self.dock.raise_()

    def notify(self, message, code=""):
        if self.dock:
            self.dock.message.setText(message + (" [" + code + "]" if code else ""))
        if code:
            self.iface.messageBar().pushMessage(
                "SAR Tools",
                message + " [" + code + "]",
                level=Qgis.MessageLevel.Warning,
                duration=8,
            )

    def create(self, parent, name):
        if not parent or not Path(parent).is_dir():
            raise SarError("OPERATION_FOLDER", "Wybierz istniejący folder nadrzędny operacji.")
        path = create_operation(parent, name)
        self.settings.setValue("sar_tools/parent_folder", parent)
        if not self.iface.addProject(str(path)):
            self.notify("Utworzono operację, ale nie otwarto projektu. Plik: " + str(path))
            return
        self.project_loaded()
        self.notify("Operacja gotowa. Warstwy robocze zapisano w GeoPackage.")
        if self.dock.auto_maps.isChecked():
            self.load_maps([s["id"] for s in self.sources])

    def open(self):
        path, _ = QFileDialog.getOpenFileName(
            self.dock,
            "Otwórz operację SAR",
            self.dock.folder_edit.text(),
            "Projekt QGIS (*.qgz *.qgs)",
        )
        if path:
            if not (Path(path).parent / "operation.json").is_file():
                raise SarError(
                    "OPERATION_MANIFEST",
                    "Ten folder nie zawiera operacji SAR (brak operation.json).",
                )
            if self.iface.addProject(path):
                operation_path(self.project)
                self.project_loaded()
                self.notify("Otwarto operację.")

    def save(self):
        operation_path(self.project)
        if not self.project.write():
            raise SarError("OPERATION_SAVE", "Nie udało się zapisać projektu.")
        editing = any(
            getattr(layer, "isModified", lambda: False)()
            for layer in self.project.mapLayers().values()
        )
        self.notify(
            "Zapisano projekt. Zapisz także trwające edycje warstw."
            if editing
            else "Zapisano projekt."
        )

    def restore(self):
        restore_layers(self.project)
        self.save()

    def project_cleared(self, *_):
        self.maps.cancel()
        self.search.cancel()
        self.locations.clear()
        self.results = []
        self.dock.show_results([])
        for source in self.sources:
            self.dock.map_status(source["id"], "Do dodania")
        self.dock.operation_label.setText("Brak otwartej operacji SAR")

    def project_loaded(self, *_):
        operation_id, _ = self.project.readEntry("sar", "operation_id", "")
        self.dock.operation_label.setText(
            "Operacja: " + self.project.title() if operation_id else "Brak otwartej operacji SAR"
        )
        self.sync()

    def sync(self, *_):
        self.dock.sync_maps(self.project.mapLayers().values(), self.project.layerTreeRoot())
        visible = []
        for layer in self.project.mapLayers().values():
            node = self.project.layerTreeRoot().findLayer(layer.id())
            if layer.customProperty("sar/source", "") and node and node.isVisible():
                credit = layer.attribution()
                if credit and credit not in visible:
                    visible.append(credit)
        if hasattr(self, "attribution"):
            self.attribution.setText(" • ".join(visible))
            self.attribution.adjustSize()
            self.attribution.move(
                8, max(8, self.iface.mapCanvas().height() - self.attribution.height() - 8)
            )
            self.attribution.raise_()
            self.attribution.setVisible(bool(visible))

    def load_maps(self, ids):
        sources = [dict(s) for s in self.sources if s["id"] in ids]
        if len(sources) == 1:
            sources[0]["default_visible"] = True
        self.maps.add(sources)
        self.notify("Mapy są dodawane w tle. Możesz pracować dalej.")

    def find_source(self, source):
        return next(
            (
                layer
                for layer in self.project.mapLayers().values()
                if layer.customProperty("sar/source", "") == source
            ),
            None,
        )

    def visibility(self, source, visible):
        layer = self.find_source(source)
        if layer:
            self.project.layerTreeRoot().findLayer(layer.id()).setItemVisibilityChecked(visible)
        elif visible:
            self.load_maps([source])
        self.sync()

    def opacity(self, source, value):
        layer = self.find_source(source)
        if layer and layer.renderer():
            layer.renderer().setOpacity(value / 100)
            layer.triggerRepaint()
            self.project.setDirty(True)

    def maps_settled(self):
        if self.project.write():
            self.notify(
                "Zakończono dodawanie map i zapisano projekt. "
                "Status każdego źródła jest w katalogu."
            )
        else:
            raise SarError("OPERATION_SAVE", "Dodano mapy, ale nie udało się zapisać projektu.")
        self.sync()

    def search_address(self, query):
        self.results = []
        self.dock.show_results([])
        self.locations.clear()
        self.search.search(query)

    def search_failed(self, code, message):
        self.dock.search_status.setText(message)
        self.notify(message, code)

    def got_results(self, results):
        self.results = results
        self.dock.show_results(results)

    def selected_result(self, index):
        if index < 0 or index >= len(self.results):
            raise SarError("ADDRESS_SELECTION", "Najpierw wyszukaj adres i wybierz wynik.")
        return self.results[index]

    def locate(self, index):
        self.locations.show(self.selected_result(index))

    def save_lkp(self, index):
        operation_path(self.project)
        result = self.selected_result(index)
        self.locations.show(result)
        dialog = LkpDialog(result, self.dock)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.locations.save_lkp(result, dialog.details())
            self.diagnostics.event("lkp_created")
            self.save()
            self.notify("Zapisano LKP wraz ze źródłem informacji i poziomem pewności.")

    def add_dem(self):
        operation_path(self.project)
        path, _ = QFileDialog.getOpenFileName(
            self.dock,
            "Dodaj raster wysokościowy",
            "",
            "Raster wysokości (*.tif *.tiff *.hgt *.asc *.vrt);;Wszystkie pliki (*)",
        )
        if not path:
            return
        layer = QgsRasterLayer(path, Path(path).stem, "gdal")
        if not layer.isValid() or not layer.crs().isValid():
            raise SarError(
                "DEM_INVALID", "Nie można otworzyć rastra albo brakuje układu współrzędnych."
            )
        band, ok = QInputDialog.getInt(
            self.dock,
            "Pasmo z wysokością",
            "Numer pasma zawierającego wysokość w metrach:",
            1,
            1,
            layer.bandCount(),
        )
        if not ok:
            return
        properties = layer.elevationProperties()
        properties.setEnabled(True)
        properties.setBandNumber(band)
        layer.setCustomProperty("sar/elevation", True)
        self.project.addMapLayer(layer, False)
        ensure_groups(self.project)["elevation"].addLayer(layer).setItemVisibilityChecked(False)
        self.save()
        self.notify(
            "Dodano dane do profili. Raster pozostaje w wybranej lokalizacji "
            "— zachowaj go razem z operacją."
        )

    def profile(self):
        if not any(
            isinstance(layer, QgsRasterLayer) and layer.elevationProperties().isEnabled()
            for layer in self.project.mapLayers().values()
        ):
            raise SarError("DEM_REQUIRED", "Najpierw dodaj lokalny model wysokości.")
        action = self.iface.mainWindow().findChild(QAction, "mActionElevationProfile")
        if action is None:
            raise SarError(
                "PROFILE_UNAVAILABLE",
                "W tej wersji QGIS otwórz profil z menu Widok → Profile wysokościowe.",
            )
        action.trigger()

    def open_link(self, key):
        links = {
            "nmt": "https://www.geoportal.gov.pl/pl/dane/numeryczny-model-terenu-nmt/",
            "nasa": "https://search.earthdata.nasa.gov/search?q=NASADEM_HGT",
            "google_docs": "https://developers.google.com/maps/comms/eea/map-tiles",
        }
        if key == "google":
            canvas = self.iface.mapCanvas()
            point = QgsCoordinateTransform(
                canvas.mapSettings().destinationCrs(),
                QgsCoordinateReferenceSystem("EPSG:4326"),
                self.project,
            ).transform(QgsPointXY(canvas.center()))
            url = "https://www.google.com/maps/search/?" + urlencode(
                {"api": "1", "query": "%.6f,%.6f" % (point.y(), point.x())}
            )
        else:
            url = links[key]
        QDesktopServices.openUrl(QUrl(url))

    def health(self):
        providers = QgsProviderRegistry.instance().providerList()
        return {
            "qgis": Qgis.QGIS_VERSION,
            "ogr": "ogr" in providers,
            "gdal": "gdal" in providers,
            "wms_wmts_xyz": "wms" in providers,
            "epsg_2180": QgsCoordinateReferenceSystem("EPSG:2180").isValid(),
            "grass_optional": bool(QgsApplication.processingRegistry().providerById("grass")),
        }

    def show_health(self):
        state = self.health()
        self.dock.health_label.setText(
            "QGIS "
            + state["qgis"]
            + "\n"
            + "\n".join(
                label + (": OK" if state[key] else ": niedostępne")
                for key, label in (
                    ("ogr", "Dane wektorowe"),
                    ("gdal", "Rastry"),
                    ("wms_wmts_xyz", "Mapy online"),
                    ("epsg_2180", "Układ Polski EPSG:2180"),
                )
            )
            + "\nGRASS: opcjonalny, niewymagany w 0.1"
        )

    def set_developer(self, enabled):
        self.settings.setValue("sar_tools/developer", enabled)
        self.diagnostics.logger.setLevel(logging.DEBUG if enabled else logging.INFO)
        if enabled:
            self.notify("Logi: " + str(self.diagnostics.directory))

    def export_diagnostics(self):
        path, _ = QFileDialog.getSaveFileName(
            self.dock,
            "Zapisz nowy pakiet diagnostyczny",
            "sar-diagnostyka.zip",
            "Archiwum ZIP (*.zip)",
        )
        if not path:
            return
        if not path.lower().endswith(".zip"):
            path += ".zip"
        if Path(path).exists():
            raise SarError("DIAGNOSTIC_EXISTS", "Plik już istnieje. Wybierz nową nazwę pakietu.")
        self.diagnostics.export(path, self.health())
        self.notify("Zapisano pakiet diagnostyczny.")

    def unload(self):
        if self.closed:
            return
        self.closed = True
        self.search.cancel()
        self.maps.close()
        self.locations.clear()
        for signal, slot in self.connections:
            try:
                signal.disconnect(slot)
            except (RuntimeError, TypeError):
                pass
        self.connections.clear()
        self.iface.removePluginMenu("SAR Tools", self.action)
        self.iface.removeToolBarIcon(self.action)
        if self.action:
            self.action.deleteLater()
        if self.dock:
            self.iface.removeDockWidget(self.dock)
            self.dock.deleteLater()
        if hasattr(self, "attribution"):
            self.attribution.deleteLater()
        self.diagnostics.event("plugin_unloaded")
        self.diagnostics.close()
