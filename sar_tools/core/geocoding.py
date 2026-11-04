"""GUGiK UUG JSON contract, kept independent of Qt and networking."""

import json
import math
from dataclasses import dataclass
from urllib.parse import urlencode

from .errors import SarError

ENDPOINT = "https://services.gugik.gov.pl/uug/"


@dataclass(frozen=True)
class AddressResult:
    label: str
    longitude: float
    latitude: float
    kind: str
    accuracy: str
    source: str = "GUGiK UUG"


def address_url(query):
    query = query.strip()
    if len(query) < 3 or len(query) > 250:
        raise SarError("ADDRESS_QUERY", "Wpisz adres o długości od 3 do 250 znaków.")
    return ENDPOINT + "?" + urlencode({"request": "GetAddress", "address": query, "srid": "4326"})


def parse_results(payload):
    try:
        data = json.loads(payload)
    except (ValueError, UnicodeError) as exc:
        raise SarError("ADDRESS_FORMAT", "Usługa adresowa zwróciła niepoprawną odpowiedź.") from exc
    if not isinstance(data, dict) or "results" not in data:
        raise SarError("ADDRESS_FORMAT", "Nie rozpoznano odpowiedzi usługi adresowej.")
    rows = data["results"]
    if rows is None:
        rows = []
    if isinstance(rows, dict):
        rows = list(rows.values())
    if not isinstance(rows, list):
        raise SarError("ADDRESS_FORMAT", "Nie rozpoznano listy znalezionych adresów.")
    results = []
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        try:
            lon, lat = float(row["x"]), float(row["y"])
        except (KeyError, TypeError, ValueError):
            continue
        if not (
            math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90
        ):
            continue
        city = str(row.get("city") or "")
        street = str(row.get("street") or "")
        number = str(row.get("number") or "")
        label = ", ".join(filter(None, [city, " ".join(filter(None, [street, number]))]))
        region = str(row.get("jednostka") or "").strip("{}")
        if region:
            label += " — " + region.replace(",", ", ")
        kind = "adres" if number else ("ulica" if street else "miejscowość")
        results.append(
            AddressResult(label or "Wynik UUG", lon, lat, kind, str(row.get("accuracy") or ""))
        )
    if rows and not results:
        raise SarError(
            "ADDRESS_COORDINATES", "Odpowiedź nie zawiera poprawnych współrzędnych WGS84."
        )
    return results
