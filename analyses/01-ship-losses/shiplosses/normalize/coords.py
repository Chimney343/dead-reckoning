"""Coordinate parsing and validation (plan section 5.2)."""

from __future__ import annotations

import json
import math
import re

from shapely.geometry import shape

_DM = re.compile(r"^\s*(\d+)\s+(\d+(?:\.\d+)?)\s*([NSEW])\s*$", re.IGNORECASE)


def valid(lat: object, lon: object) -> bool:
    """True when the pair is a finite WGS84 coordinate."""
    if lat is None or lon is None:
        return False
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return False
    if math.isnan(lat_f) or math.isnan(lon_f):
        return False
    return abs(lat_f) <= 90 and abs(lon_f) <= 180


def parse_degrees_minutes(text: object) -> float | None:
    """UKHO degrees and decimal minutes, e.g. ``5 33.535 S`` -> -5.558917."""
    if text is None:
        return None
    match = _DM.match(str(text))
    if not match:
        return None
    degrees = float(match[1])
    minutes = float(match[2])
    hemisphere = match[3].upper()
    value = degrees + minutes / 60.0
    if hemisphere in {"S", "W"}:
        value = -value
    return value


def parse_zenodo_coordinates(raw: object) -> tuple[float, float] | None:
    """Zenodo ``lat;lon`` with an optional trailing U+FEFF."""
    if raw is None:
        return None
    text = str(raw).replace("\ufeff", "").strip()
    if not text:
        return None
    parts = text.split(";")
    if len(parts) != 2:
        return None
    try:
        lat = float(parts[0].strip())
        lon = float(parts[1].strip())
    except ValueError:
        return None
    return (lat, lon) if valid(lat, lon) else None


def parse_pair(lat: object, lon: object) -> tuple[float, float] | None:
    """Two numeric fields; WIID's ``(0, 0)`` means no location."""

    def _num(value: object) -> float | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or text.casefold() in {"nan", "none", "n/a", "null"}:
            return None
        try:
            return float(text)
        except ValueError:
            return None

    lat_f, lon_f = _num(lat), _num(lon)
    if lat_f is None or lon_f is None:
        return None
    if lat_f == 0.0 and lon_f == 0.0:
        return None
    if not valid(lat_f, lon_f):
        return None
    return (lat_f, lon_f)


def _first_coordinate(node: object):
    """Yield ``(lon, lat)`` pairs from an arbitrarily nested GeoJSON structure."""
    if isinstance(node, (list, tuple)):
        if (
            len(node) >= 2
            and isinstance(node[0], (int, float))
            and isinstance(node[1], (int, float))
        ):
            yield (float(node[0]), float(node[1]))
        else:
            for item in node:
                yield from _first_coordinate(item)


def geojson_centroid(raw: object) -> tuple[float, float] | None:
    """Centroid of a GeoJSON geometry string; a one-vertex polygon keeps its vertex."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        payload = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    try:
        geometry = shape(payload)
    except (ValueError, TypeError, AttributeError):
        geometry = None
    if geometry is not None and not geometry.is_empty:
        centroid = geometry.centroid
        if valid(centroid.y, centroid.x):
            return (centroid.y, centroid.x)
    for lon, lat in _first_coordinate(payload.get("coordinates")):
        if valid(lat, lon):
            return (lat, lon)
    return None
