"""Offline-first geocoding (plan section 5.6)."""

from __future__ import annotations

import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from .normalize import names

UNCERTAINTY = {"surveyed": 0.1, "reported": 5.0, "place": 10.0, "region": 250.0}

_LEADING_PREP = re.compile(r"^(?:at|on|near|off|in|by)\s+", re.IGNORECASE)


def _norm(text: object) -> str:
    value = names.normalize_name(text)
    return _LEADING_PREP.sub("", value).strip()


@dataclass(frozen=True)
class Hit:
    lat: float
    lon: float
    precision: str
    method: str
    uncertainty_km: float | None = None

    def uncertainty(self) -> float:
        if self.uncertainty_km is not None:
            return self.uncertainty_km
        return UNCERTAINTY.get(self.precision, 10.0)


class Gazetteers:
    """Offline gazetteer lookups; every layer is optional."""

    def __init__(self, data_dir: Path, raw_root: Path) -> None:
        self.data_dir = data_dir
        self.raw_root = raw_root
        self.overrides = self._load_overrides()
        self.voc_places = self._load_ibm_gazetteer(raw_root)
        self.battles = self._load_battles()
        self.geonames = self._load_geonames(raw_root)
        self.marines = self._load_marine(raw_root)

    # ------------------------------------------------------------- loaders
    def _load_overrides(self) -> list[dict]:
        path = self.data_dir / "place_overrides.csv"
        if not path.exists():
            return []
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        return frame.to_dict("records")

    @staticmethod
    def _load_ibm_gazetteer(raw_root: Path) -> list[dict]:
        archive = raw_root / "ibm-maritime-archives" / "chuk-mcp-maritime-archives-HEAD.zip"
        if not archive.exists():
            return []
        with zipfile.ZipFile(archive) as bundle:
            member = next(
                (name for name in bundle.namelist() if name.endswith("data/gazetteer.json")),
                None,
            )
            if not member:
                return []
            data = json.loads(bundle.read(member))
        return data if isinstance(data, list) else []

    def _load_battles(self) -> list[dict]:
        path = self.data_dir / "battles.csv"
        if not path.exists():
            return []
        frame = pd.read_csv(path, dtype=str, keep_default_na=False)
        return frame.to_dict("records")

    @staticmethod
    def _load_geonames(raw_root: Path) -> dict[str, list[tuple]]:
        directory = raw_root / "geonames"
        if not directory.exists():
            return {}
        index: dict[str, list[tuple]] = {}
        for path in sorted(directory.glob("*.txt")):
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    parts = line.rstrip("\n").split("\t")
                    if len(parts) < 9:
                        continue
                    name, ascii_name, alternates = parts[1], parts[2], parts[3]
                    try:
                        lat, lon = float(parts[4]), float(parts[5])
                    except ValueError:
                        continue
                    record = (lat, lon, parts[6], parts[8], parts[10] if len(parts) > 10 else "")
                    keys = {_norm(name), _norm(ascii_name)}
                    keys.update(_norm(alt) for alt in alternates.split(",")[:4] if alt)
                    for key in keys:
                        if key:
                            index.setdefault(key, []).append(record)
        return index

    @staticmethod
    def _load_marine(raw_root: Path) -> list[tuple[str, float, float]]:
        archive = (
            raw_root
            / "naturalearth"
            / "ne_10m_geography_marine_polys.zip"
        )
        if not archive.exists():
            return []
        try:
            import geopandas as gpd
        except ImportError:
            return []
        frame = gpd.read_file(f"zip://{archive}")
        result = []
        for _, row in frame.iterrows():
            label = row.get("name") or row.get("namealt")
            geometry = row.geometry
            if not label or geometry is None or geometry.is_empty:
                continue
            point = geometry.representative_point()
            result.append((_norm(label), point.y, point.x))
        return result

    # ------------------------------------------------------------- lookups
    def override(self, text: object, source: str) -> Hit | None:
        key = _norm(text)
        if not key:
            return None
        for row in self.overrides:
            if _norm(row.get("location_text")) != key:
                continue
            row_source = (row.get("source") or "*").strip()
            if row_source not in {"*", source}:
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            precision = (row.get("precision") or "place").strip()
            return Hit(lat, lon, precision, "override", None)
        return None

    def voc_place(self, text: object) -> Hit | None:
        key = _norm(text)
        if not key:
            return None
        for entry in self.voc_places:
            names = [entry.get("name", "")] + list(entry.get("aliases", []))
            if key not in {_norm(name) for name in names}:
                continue
            lat, lon = entry.get("lat"), entry.get("lon")
            if lat is None or lon is None:
                continue
            return Hit(float(lat), float(lon), "place", "gazetteer:ibm", None)
        return None

    def battle(self, text: object) -> Hit | None:
        key = _norm(text)
        if not key:
            return None
        for row in self.battles:
            if _norm(row.get("battle")) != key:
                continue
            try:
                lat, lon = float(row["lat"]), float(row["lon"])
            except (KeyError, TypeError, ValueError):
                continue
            return Hit(lat, lon, "place", "gazetteer:battles", None)
        return None

    def marine(self, text: object) -> Hit | None:
        key = _norm(text)
        if not key:
            return None
        for label, lat, lon in self.marines:
            if label == key:
                return Hit(lat, lon, "region", "marine_area", None)
        return None

    def geoname(
        self,
        text: object,
        *,
        countries: set[str] | None = None,
        admin1: str | None = None,
    ) -> Hit | None:
        key = _norm(text)
        if not key or key not in self.geonames:
            return None
        candidates = self.geonames[key]
        if countries:
            candidates = [c for c in candidates if c[3] in countries]
        if admin1:
            candidates = [c for c in candidates if str(c[4]).casefold() == admin1.casefold()]
        if not candidates:
            return None
        rank = {"H": 0, "T": 1, "P": 2}
        candidates.sort(key=lambda c: rank.get(c[2], 3))
        lats = [c[0] for c in candidates]
        lons = [c[1] for c in candidates]
        if max(lats) - min(lats) > 0.5 or max(lons) - min(lons) > 0.5:
            return None
        lat, lon = candidates[0][0], candidates[0][1]
        return Hit(lat, lon, "place", "gazetteer:geonames", None)


def _context(row: pd.Series) -> tuple[set[str] | None, str | None]:
    source = row.get("source")
    if source == "ireland-wiid":
        return {"IE", "GB"}, "Northern Ireland"
    if source == "novascotia-shipwrecks":
        return {"CA"}, "Nova Scotia"
    if source == "wa-shipwrecks":
        return {"AU"}, None
    return None, None


def geocode_losses(
    losses: pd.DataFrame,
    gaz: Gazetteers,
    *,
    unresolved: dict[str, int] | None = None,
) -> pd.DataFrame:
    """Fill coordinates and precision for rows that lack them."""
    if losses.empty:
        return losses
    unresolved = unresolved if unresolved is not None else {}
    for index, row in losses.iterrows():
        if pd.notna(row.get("lat")) and pd.notna(row.get("lon")):
            continue
        text = row.get("location_text")
        if not isinstance(text, str) or not text.strip():
            continue
        source = row.get("source")
        hit = gaz.override(text, source) if source else None
        if hit is None:
            hit = gaz.battle(text)
        if hit is None and source == "dutch-asiatic-shipping":
            hit = gaz.voc_place(text)
        if hit is None:
            countries, admin1 = _context(row)
            if countries is not None or admin1 is not None:
                hit = gaz.geoname(text, countries=countries, admin1=admin1)
        if hit is None:
            hit = gaz.marine(text)
        if hit is None:
            key = str(text).strip()
            unresolved[key] = unresolved.get(key, 0) + 1
            continue
        losses.at[index, "lat"] = hit.lat
        losses.at[index, "lon"] = hit.lon
        losses.at[index, "location_precision"] = hit.precision
        losses.at[index, "uncertainty_km"] = hit.uncertainty()
        losses.at[index, "geocode_method"] = hit.method
    return losses


def geocode_online(
    losses: pd.DataFrame,
    cache_path: Path,
    contact: str,
    *,
    max_requests: int = 2000,
) -> pd.DataFrame:
    """Optional Nominatim pass (plan section 5.6): <=1 request/s, cached, opt-in."""
    import csv
    import time

    import httpx

    cache: dict[str, tuple[float, float] | None] = {}
    if cache_path.exists():
        with cache_path.open(encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle):
                try:
                    cache[row["location_text"]] = (float(row["lat"]), float(row["lon"]))
                except (KeyError, TypeError, ValueError):
                    continue
    made = 0
    with httpx.Client(
        headers={"User-Agent": f"dead-reckoning ({contact})"}, timeout=10.0
    ) as client:
        for index, row in losses.iterrows():
            if pd.notna(row.get("lat")) and pd.notna(row.get("lon")):
                continue
            text = row.get("location_text")
            if not isinstance(text, str) or not text.strip():
                continue
            key = text.strip()
            if key not in cache:
                if made >= max_requests:
                    break
                try:
                    response = client.get(
                        "https://nominatim.openstreetmap.org/search",
                        params={"q": key, "format": "json", "limit": 1},
                    )
                    response.raise_for_status()
                    results = response.json()
                except httpx.HTTPError:
                    break
                made += 1
                time.sleep(1.0)
                if not results:
                    cache[key] = None
                    continue
                cache[key] = (float(results[0]["lat"]), float(results[0]["lon"]))
            point = cache.get(key)
            if point:
                losses.at[index, "lat"], losses.at[index, "lon"] = point
                losses.at[index, "location_precision"] = "place"
                losses.at[index, "uncertainty_km"] = 10.0
                losses.at[index, "geocode_method"] = "gazetteer:nominatim"

    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with cache_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(["location_text", "lat", "lon"])
        for key, point in sorted(cache.items()):
            if point:
                writer.writerow([key, point[0], point[1]])
    return losses
