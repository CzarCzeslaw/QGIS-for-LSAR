"""Versioned operation schema. Names are presentation; keys are stable identities."""

from dataclasses import dataclass

SCHEMA_VERSION = 1
CRS = "EPSG:2180"
FOLDERS = ("raw", "processed", "derived", "cache", "exports", "logs")
GROUPS = (
    ("planning", "01 Planowanie"),
    ("to_gps", "02 Do GPS"),
    ("from_gps", "03 Z GPS"),
    ("maps", "04 Mapy i teren"),
)
MAP_GROUPS = (
    ("forest", "Lasy i nakładki tematyczne"),
    ("relief", "Rzeźba terenu"),
    ("elevation", "Dane wysokościowe do profili"),
    ("basemaps", "Podkłady"),
)


@dataclass(frozen=True)
class LayerSpec:
    key: str
    name: str
    geometry: str
    group: str
    color: str
    symbol: str = "circle"


LAYERS = (
    LayerSpec("lkp", "LKP — ostatnia znana lokalizacja", "Point", "planning", "#d32f2f", "star"),
    LayerSpec("locations", "Inne zgłoszone lokalizacje", "Point", "planning", "#ee8b23", "diamond"),
    LayerSpec("operational_points", "Punkty operacyjne", "Point", "planning", "#1565c0", "square"),
    LayerSpec(
        "hazards", "Zagrożenia i miejsca do sprawdzenia", "Point", "planning", "#a438a8", "triangle"
    ),
    LayerSpec("planned_routes", "Planowane trasy", "LineString", "planning", "#e08021"),
    LayerSpec("search_lines", "Linie przeszukania", "LineString", "planning", "#2166ac"),
    LayerSpec("sectors", "Sektory", "Polygon", "planning", "#d58816"),
    LayerSpec("search_area", "Obszar poszukiwań", "Polygon", "planning", "#c43333"),
    LayerSpec("gps_out_points", "Punkty do wysłania", "Point", "to_gps", "#137c6c", "square"),
    LayerSpec("gps_out_routes", "Trasy do wysłania", "LineString", "to_gps", "#137c6c"),
    LayerSpec(
        "gps_out_tracks", "Ślady prowadzące i granice sektorów", "LineString", "to_gps", "#268c86"
    ),
    LayerSpec("gps_in_points", "Zapisane punkty", "Point", "from_gps", "#6f42b5", "diamond"),
    LayerSpec("gps_in_tracks", "Zarejestrowane ślady", "LineString", "from_gps", "#6f42b5"),
    LayerSpec("gps_in_routes", "Zaimportowane trasy", "LineString", "from_gps", "#9467bd"),
)

# Timestamps use date/time fields; remaining attributes (including UUIDs) are text.
FIELDS = (
    ("uid", "Identyfikator"),
    ("name", "Nazwa"),
    ("status", "Status"),
    ("source", "Źródło informacji"),
    ("confidence", "Pewność informacji"),
    ("observed_at", "Czas zdarzenia / obserwacji"),
    ("created_at", "Utworzono"),
    ("notes", "Uwagi"),
    ("device_id", "Urządzenie"),
    ("import_id", "Identyfikator importu"),
    ("source_uid", "Identyfikator obiektu źródłowego"),
)
