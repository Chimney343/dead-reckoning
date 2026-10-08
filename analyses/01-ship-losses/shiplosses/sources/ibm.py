"""IBM chuk-mcp-maritime-archives losses (plan sections 2.3 and 9)."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

from ..normalize import causes, dates, polities
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "ibm-maritime-archives"

_CURATED = {
    "carreira_wrecks.json": "carreira",
    "eic_wrecks.json": "eic",
    "galleon_wrecks.json": "galleon",
    "soic_wrecks.json": "soic",
}
_ARCHIVE_POLITY = {
    "carreira": "Portugal",
    "eic": "Great Britain",
    "galleon": "Spain",
    "soic": "Sweden",
}


def _load(archive: zipfile.ZipFile, suffix: str):
    for name in archive.namelist():
        if name.endswith(suffix):
            return json.loads(archive.read(name).decode("utf-8"))
    return None


def _position(record: dict) -> tuple[float, float, str, float] | None:
    position = record.get("position") or {}
    lat, lon = position.get("lat"), position.get("lon")
    if lat is None or lon is None:
        return None
    try:
        lat_f, lon_f = float(lat), float(lon)
    except (TypeError, ValueError):
        return None
    uncertainty = position.get("uncertainty_km")
    try:
        uncertainty_f = float(uncertainty)
    except (TypeError, ValueError):
        uncertainty_f = 5.0
    precision = "surveyed" if uncertainty_f <= 1.0 else "reported"
    return lat_f, lon_f, precision, uncertainty_f


def _wreck_rows(records: list[dict], meta: dict) -> list[dict]:
    records_out: list[dict] = []
    for index, record in enumerate(records):
        record_id = first(record.get("wreck_id")) or str(index)
        cause = causes.classify(first(record.get("loss_cause")))
        parsed = dates.parse_date(record.get("loss_date"))
        place = first(record.get("loss_location")) or None
        record_doc = meta["source"]
        records_out.append(
            {
                "source": record_doc,
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": first(record.get("ship_name")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "location_text": place,
                "location_precision": "place" if place else "none",
                "uncertainty_km": 10.0 if place else None,
                "origin_raw": "VOC",
                "origin_polity": "Dutch Republic",
                "origin_basis": "flag_assumed",
                "flag_at_loss_raw": "Dutch Republic",
                "flag_at_loss_polity": "Dutch Republic",
                "owner_at_loss": "VOC",
                "cause_raw": first(record.get("loss_cause")) or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "route_from": first(record.get("departure_port")) or None,
                "route_to": first(record.get("destination_port")) or None,
                "raw": {
                    "wreck_id": record.get("wreck_id"),
                    "voyage_id": record.get("voyage_id"),
                    "loss_cause": record.get("loss_cause"),
                    "loss_date": record.get("loss_date"),
                    "loss_location": record.get("loss_location"),
                    "region": record.get("region"),
                    "status": record.get("status"),
                    "particulars": record.get("particulars"),
                    "captain": record.get("captain"),
                },
            }
        )
    return records_out


def _curated_rows(records: list[dict], archive_name: str, meta: dict) -> list[dict]:
    records_out: list[dict] = []
    polity_name = _ARCHIVE_POLITY.get(archive_name, "")
    polity = polities.lookup(polity_name) if polity_name else None
    for index, record in enumerate(records):
        if record.get("is_curated") is not True:
            continue
        record_id = first(record.get("wreck_id")) or f"{archive_name}:{index}"
        cause = causes.classify(first(record.get("loss_cause")))
        parsed = dates.parse_date(record.get("loss_date"))
        place = first(record.get("loss_location")) or None
        position = _position(record)
        if position:
            lat, lon, precision, uncertainty = position
        else:
            lat = lon = None
            precision = "place" if place else "none"
            uncertainty = 10.0 if place else None
        records_out.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": first(record.get("ship_name")) or None,
                "ship_type": None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": lat,
                "lon": lon,
                "location_text": place,
                "location_precision": precision,
                "uncertainty_km": uncertainty,
                "geocode_method": "source_coords" if position else "none",
                "origin_raw": polity_name or None,
                "origin_polity": polity[0] if polity else None,
                "origin_basis": "flag_assumed" if polity else None,
                "flag_at_loss_raw": polity_name or None,
                "flag_at_loss_polity": polity[0] if polity else None,
                "cause_raw": first(record.get("loss_cause")) or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "raw": {
                    "wreck_id": record.get("wreck_id"),
                    "archive": record.get("archive"),
                    "voyage_id": record.get("voyage_id"),
                    "loss_cause": record.get("loss_cause"),
                    "loss_date": record.get("loss_date"),
                    "loss_location": record.get("loss_location"),
                    "region": record.get("region"),
                    "status": record.get("status"),
                    "position": record.get("position"),
                    "particulars": record.get("particulars"),
                },
            }
        )
    return records_out


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "ibm-maritime-archives"
    if not directory.exists():
        return Extract(empty_losses(), empty_events())
    archive_path = directory / "chuk-mcp-maritime-archives-HEAD.zip"
    if not archive_path.exists():
        candidates = sorted(directory.glob("*.zip"))
        archive_path = candidates[0] if candidates else None
    if archive_path is None:
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T3",
        licence="Apache-2.0",
        redistribute=True,
        url="https://github.com/IBM/chuk-mcp-maritime-archives",
    )

    rows: list[dict] = []
    with zipfile.ZipFile(archive_path) as archive:
        wrecks = _load(archive, "/data/wrecks.json")
        if wrecks:
            rows.extend(_wreck_rows(wrecks, meta))
        for filename, archive_name in _CURATED.items():
            records = _load(archive, f"/data/{filename}")
            if records:
                rows.extend(_curated_rows(records, archive_name, meta))

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
