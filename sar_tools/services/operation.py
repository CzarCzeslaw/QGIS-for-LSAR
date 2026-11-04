import json
import os
import re
import shutil
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path

from qgis.core import (
    Qgis,
    QgsCoordinateReferenceSystem,
    QgsDefaultValue,
    QgsEditorWidgetSetup,
    QgsField,
    QgsFillSymbol,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProject,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsTextBufferSettings,
    QgsTextFormat,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
)
from qgis.PyQt.QtCore import QMetaType
from qgis.PyQt.QtGui import QColor

from .. import __version__
from ..core.errors import SarError
from ..core.schema import CRS, FIELDS, FOLDERS, GROUPS, LAYERS, MAP_GROUPS, SCHEMA_VERSION


def folder_name(name):
    name = re.sub(r"[^\w .-]", "_", name.strip(), flags=re.UNICODE).strip(" .")
    if not name or name in (".", "..") or len(name) > 100:
        raise SarError("OPERATION_NAME", "Podaj nazwę operacji (maksymalnie 100 znaków).")
    return name


def operation_path(project):
    operation_id, _ = project.readEntry("sar", "operation_id", "")
    if not operation_id or not project.fileName():
        raise SarError("OPERATION_REQUIRED", "Najpierw utwórz lub otwórz operację SAR.")
    root = Path(project.fileName()).resolve().parent
    try:
        manifest = json.loads((root / "operation.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise SarError(
            "OPERATION_MANIFEST", "Nie znaleziono poprawnego pliku operation.json."
        ) from exc
    if manifest.get("id") != operation_id or manifest.get("schema_version") != SCHEMA_VERSION:
        raise SarError("OPERATION_VERSION", "Projekt ma niezgodny identyfikator lub wersję danych.")
    if not (root / "operation.gpkg").is_file():
        raise SarError("OPERATION_DATA", "Brakuje operation.gpkg. Przywróć plik danych operacji.")
    return root


def ensure_groups(project):
    root = project.layerTreeRoot()

    def ensure(parent, key, name):
        existing = next(
            (g for g in parent.children() if g.customProperty("sar/group", "") == key), None
        )
        if existing is None:
            existing = parent.addGroup(name)
            existing.setCustomProperty("sar/group", key)
            if key == "basemaps":
                existing.setIsMutuallyExclusive(True)
        return existing

    result = {key: ensure(root, key, name) for key, name in GROUPS}
    for key, name in MAP_GROUPS:
        result[key] = ensure(result["maps"], key, name)
    return result


def style_layer(layer, spec):
    if spec.geometry == "Point":
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": spec.symbol,
                "color": spec.color,
                "size": "4",
                "outline_color": "white",
                "outline_width": "0.4",
            }
        )
    elif spec.geometry == "LineString":
        symbol = QgsLineSymbol.createSimple(
            {
                "line_color": spec.color,
                "line_width": "0.7",
                "line_style": "dash" if spec.group == "planning" else "solid",
            }
        )
    else:
        symbol = QgsFillSymbol.createSimple(
            {
                "color": "255,255,255,0",
                "outline_color": spec.color,
                "outline_width": "0.7",
                "outline_style": "dash",
            }
        )
    layer.renderer().setSymbol(symbol)
    label = QgsPalLayerSettings()
    label.fieldName = "name"
    fmt = QgsTextFormat()
    fmt.setSize(10)
    fmt.setColor(QColor(spec.color))
    buffer = QgsTextBufferSettings()
    buffer.setEnabled(True)
    buffer.setSize(0.9)
    buffer.setColor(QColor("white"))
    fmt.setBuffer(buffer)
    label.setFormat(fmt)
    layer.setLabeling(QgsVectorLayerSimpleLabeling(label))
    layer.setLabelsEnabled(True)
    for field, alias in FIELDS:
        layer.setFieldAlias(layer.fields().indexOf(field), alias)
    for field, expression in (("uid", "uuid()"), ("status", "'roboczy'"), ("created_at", "now()")):
        layer.setDefaultValueDefinition(layer.fields().indexOf(field), QgsDefaultValue(expression))
    for field in ("uid", "created_at"):
        config = layer.editFormConfig()
        config.setReadOnly(layer.fields().indexOf(field), True)
        layer.setEditFormConfig(config)
    layer.setEditorWidgetSetup(
        layer.fields().indexOf("notes"), QgsEditorWidgetSetup("TextEdit", {"IsMultiline": True})
    )
    layer.setEditorWidgetSetup(
        layer.fields().indexOf("confidence"),
        QgsEditorWidgetSetup(
            "ValueMap",
            {
                "map": [
                    {"Nieokreślona": "nieokreślona"},
                    {"Niska": "niska"},
                    {"Średnia": "średnia"},
                    {"Wysoka": "wysoka"},
                ]
            },
        ),
    )
    layer.setCustomProperty("sar/layer", spec.key)


def restore_layers(project):
    root = operation_path(project)
    groups = ensure_groups(project)
    existing = {
        layer.customProperty("sar/layer", ""): layer for layer in project.mapLayers().values()
    }
    for spec in LAYERS:
        if spec.key in existing:
            continue
        layer = QgsVectorLayer(
            str(root / "operation.gpkg") + "|layername=" + spec.key, spec.name, "ogr"
        )
        if not layer.isValid():
            raise SarError("OPERATION_LAYER", "Brakuje warstwy danych: " + spec.name)
        style_layer(layer, spec)
        project.addMapLayer(layer, False)
        groups[spec.group].addLayer(layer)


def create_operation(parent, name):
    """Build in a private staging directory, then publish without overwriting any operation."""
    parent = Path(parent).resolve()
    target = parent / folder_name(name)
    if target.exists():
        raise SarError(
            "OPERATION_EXISTS",
            "Folder o tej nazwie już istnieje. Wybierz inną nazwę lub otwórz projekt.",
        )
    staging = Path(tempfile.mkdtemp(prefix=".sar-building-", dir=parent))
    project = QgsProject()
    try:
        for folder in FOLDERS:
            (staging / folder).mkdir()
        manifest = {
            "id": str(uuid.uuid4()),
            "name": name.strip(),
            "schema_version": SCHEMA_VERSION,
            "plugin_version": __version__,
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        (staging / "operation.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        (staging / "logs" / "events.jsonl").write_text(
            json.dumps(
                {
                    "event": "operation_created",
                    "time": manifest["created_at"],
                    "plugin": __version__,
                }
            )
            + "\n",
            encoding="utf-8",
        )
        gpkg = staging / "operation.gpkg"
        for spec in LAYERS:
            memory = QgsVectorLayer(spec.geometry + "?crs=" + CRS, spec.name, "memory")
            fields = [
                QgsField(
                    key,
                    QMetaType.Type.QDateTime
                    if key in ("observed_at", "created_at")
                    else QMetaType.Type.QString,
                )
                for key, _ in FIELDS
            ]
            if not memory.dataProvider().addAttributes(fields):
                raise SarError("OPERATION_SCHEMA", "Nie udało się utworzyć pól warstwy.")
            memory.updateFields()
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = spec.key
            options.fileEncoding = "UTF-8"
            options.actionOnExistingFile = (
                QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteLayer
                if gpkg.exists()
                else QgsVectorFileWriter.ActionOnExistingFile.CreateOrOverwriteFile
            )
            result = QgsVectorFileWriter.writeAsVectorFormatV3(
                memory, str(gpkg), project.transformContext(), options
            )
            if result[0] != QgsVectorFileWriter.WriterError.NoError:
                raise SarError(
                    "OPERATION_WRITE", "Nie udało się zapisać warstw operacji: " + result[1]
                )
        project.setFileName(str(staging / "project.qgz"))
        project.setTitle(name.strip())
        project.setCrs(QgsCoordinateReferenceSystem(CRS))
        project.setFilePathStorage(Qgis.FilePathType.Relative)
        project.writeEntry("sar", "operation_id", manifest["id"])
        project.writeEntry("sar", "schema_version", SCHEMA_VERSION)
        restore_layers(project)
        project.viewSettings().setDefaultViewExtent(
            QgsReferencedRectangle(QgsRectangle(170000, 130000, 870000, 780000), project.crs())
        )
        if not project.write():
            raise SarError("OPERATION_SAVE", "Nie udało się zapisać projektu QGIS.")
        project.clear()
        if target.exists():
            raise SarError(
                "OPERATION_EXISTS", "Folder operacji pojawił się podczas zapisu. Nie nadpisano go."
            )
        os.rename(staging, target)
        return target / "project.qgz"
    except Exception:
        project.clear()
        shutil.rmtree(staging, ignore_errors=True)
        raise
