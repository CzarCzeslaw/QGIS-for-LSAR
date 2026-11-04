import uuid

from qgis.core import (
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFeature,
    QgsGeometry,
    QgsPointXY,
    QgsRectangle,
)
from qgis.gui import QgsVertexMarker
from qgis.PyQt.QtCore import QDateTime
from qgis.PyQt.QtGui import QColor

from ..core.errors import SarError
from .operation import operation_path


class LocationService:
    def __init__(self, canvas, project):
        self.canvas = canvas
        self.project = project
        self.marker = None

    def clear(self):
        if self.marker is not None:
            self.canvas.scene().removeItem(self.marker)
            self.marker = None

    def show(self, result):
        source = QgsCoordinateReferenceSystem("EPSG:4326")
        destination = self.canvas.mapSettings().destinationCrs()
        transform = QgsCoordinateTransform(source, destination, self.project)
        point = transform.transform(QgsPointXY(result.longitude, result.latitude))
        self.clear()
        marker = QgsVertexMarker(self.canvas)
        marker.setCenter(point)
        marker.setColor(QColor("#e26100"))
        marker.setIconType(QgsVertexMarker.ICON_CROSS)
        marker.setIconSize(18)
        marker.setPenWidth(3)
        self.marker = marker
        # Start with a metre-based extent even when the project uses degrees.
        metric = QgsCoordinateReferenceSystem("EPSG:2180")
        center = QgsCoordinateTransform(source, metric, self.project).transform(
            QgsPointXY(result.longitude, result.latitude)
        )
        radius = {"adres": 300, "ulica": 800, "miejscowość": 2000}.get(result.kind, 500)
        extent = QgsRectangle(
            center.x() - radius, center.y() - radius, center.x() + radius, center.y() + radius
        )
        extent = QgsCoordinateTransform(metric, destination, self.project).transformBoundingBox(
            extent
        )
        self.canvas.setExtent(extent)
        self.canvas.refresh()

    def save_lkp(self, result, details):
        operation_path(self.project)
        layer = next(
            (
                layer
                for layer in self.project.mapLayers().values()
                if layer.customProperty("sar/layer", "") == "lkp"
            ),
            None,
        )
        if layer is None or not layer.isValid():
            raise SarError("LKP_LAYER", "Brakuje warstwy LKP. Przywróć warstwy operacji.")
        if layer.isEditable():
            raise SarError(
                "LKP_EDITING",
                "Zapisz lub zakończ bieżącą edycję warstwy LKP przed dodaniem lokalizacji.",
            )
        feature = QgsFeature(layer.fields())
        point = QgsCoordinateTransform(
            QgsCoordinateReferenceSystem("EPSG:4326"), layer.crs(), self.project
        ).transform(QgsPointXY(result.longitude, result.latitude))
        feature.setGeometry(QgsGeometry.fromPointXY(point))
        for name, value in {
            "uid": str(uuid.uuid4()),
            "name": details["name"],
            "status": "roboczy",
            "source": details["source"],
            "confidence": details["confidence"],
            "created_at": QDateTime.currentDateTimeUtc(),
            "observed_at": details.get("observed_at"),
            "notes": details["notes"]
            + "\nLokalizacja: "
            + result.label
            + "\nGeokodowanie: GUGiK UUG; typ: "
            + result.kind,
        }.items():
            feature[name] = value
        if not layer.startEditing():
            raise SarError("LKP_WRITE", "Nie można rozpocząć zapisu warstwy LKP.")
        if not layer.addFeature(feature) or not layer.commitChanges():
            layer.rollBack()
            raise SarError(
                "LKP_WRITE", "Nie udało się zapisać LKP. Sprawdź dostęp do pliku danych."
            )
        layer.triggerRepaint()
        return feature
