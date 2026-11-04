"""Declarative map catalogue; QGIS URIs are built from advertised capabilities."""

import json
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from .errors import SarError


def load_catalog():
    path = Path(__file__).resolve().parents[1] / "data" / "sources.json"
    return json.loads(path.read_text(encoding="utf-8"))


def capabilities_url(source):
    parts = urlsplit(source["url"])
    params = dict(parse_qsl(parts.query))
    params.update({"SERVICE": source["type"].upper(), "REQUEST": "GetCapabilities"})
    if source["type"] == "wms":
        params["VERSION"] = "1.3.0"
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(params), ""))


def _xml(payload):
    if (
        len(payload) > 10_000_000
        or b"<!ENTITY" in payload.upper()
        or b"<!DOCTYPE" in payload.upper()
    ):
        raise SarError("MAP_CAPABILITIES", "Odrzucono nieprawidłowy opis usługi mapowej.")
    try:
        return ET.fromstring(payload)
    except ET.ParseError as exc:
        raise SarError("MAP_CAPABILITIES", "Serwer map zwrócił niepoprawny opis usługi.") from exc


def wmts_parameters(source, payload):
    root = _xml(payload)
    ns = {"w": "http://www.opengis.net/wmts/1.0", "o": "http://www.opengis.net/ows/1.1"}
    layers = root.findall(".//w:Contents/w:Layer", ns)
    if source.get("layer"):
        layers = [
            item
            for item in layers
            if item.findtext("o:Identifier", namespaces=ns) == source["layer"]
        ]
    if not layers:
        raise SarError("MAP_LAYER", "Usługa nie udostępnia oczekiwanej warstwy.")
    layer = layers[0]
    matrices = {
        m.findtext("o:Identifier", namespaces=ns): m.findtext("o:SupportedCRS", namespaces=ns)
        for m in root.findall(".//w:Contents/w:TileMatrixSet", ns)
    }
    available = []
    for link in layer.findall("w:TileMatrixSetLink/w:TileMatrixSet", ns):
        crs = matrices.get(link.text, "") or ""
        for code in (2180, 3857, 4326):
            if crs.endswith(":" + str(code)) or crs.endswith("/" + str(code)):
                available.append((code, link.text))
    if not available:
        raise SarError("MAP_CRS", "Usługa nie udostępnia obsługiwanego układu współrzędnych.")
    code, matrix = sorted(available, key=lambda pair: (2180, 3857, 4326).index(pair[0]))[0]
    styles = layer.findall("w:Style", ns)
    style = next((s for s in styles if s.get("isDefault") == "true"), styles[0] if styles else None)
    formats = [n.text for n in layer.findall("w:Format", ns)]
    image_format = "image/png" if "image/png" in formats else "image/jpeg"
    if image_format not in formats:
        raise SarError("MAP_FORMAT", "Brak obsługiwanego formatu obrazu mapy.")
    return {
        "layers": layer.findtext("o:Identifier", namespaces=ns),
        "styles": style.findtext("o:Identifier", namespaces=ns) if style is not None else "",
        "format": image_format,
        "crs": "EPSG:" + str(code),
        "tileMatrixSet": matrix,
        "url": capabilities_url(source),
    }


def wms_parameters(source, payload):
    root = _xml(payload)
    # WMS 1.1 and 1.3 differ in namespaces, so normalize tag names.
    for node in root.iter():
        node.tag = node.tag.rsplit("}", 1)[-1]
    layer_names = {node.findtext("Name") for node in root.iter("Layer")}
    requested = source.get("layers", [])
    if not requested or any(name not in layer_names for name in requested):
        raise SarError("MAP_LAYER", "Usługa nie udostępnia oczekiwanych warstw tematycznych.")
    return {
        "layers": ",".join(requested),
        "styles": ",".join("" for _ in requested),
        "format": "image/png",
        "crs": "EPSG:2180",
        "url": source["url"],
        "version": root.get("version", "1.3.0"),
        "transparent": "true",
    }
