"""INFOMAR surveyed shipwrecks (plan section 2.3)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..normalize import coords, dates
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "ireland-infomar"


def _text(value: object) -> str:
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return first(value)


def _date_value(value: object) -> object:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(value, "strftime"):
        return value.strftime("%Y-%m-%d")
    text = str(value).strip()
    if " " in text or "T" in text:
        return text.split(" ", 1)[0].split("T", 1)[0]
    return value


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "ireland-infomar"
    if not directory.exists():
        return Extract(empty_losses(), empty_events())
    archive = next(iter(sorted(directory.glob("*.zip"))), None)
    if archive is None:
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="CC-BY-4.0",
        redistribute=True,
        url="https://gsi.geodata.gov.ie/downloads/Marine/Data/Downloads/Shapefiles/IE_GSI_MI_Shipwrecks_IE_Waters_WGS84_LAT.zip",
    )

    import geopandas as gpd

    frame = gpd.read_file("zip://" + str(archive))

    rows: list[dict] = []
    seen: set[str] = set()
    for index, record in enumerate(frame.to_dict("records")):
        record_id = _text(record.get("nms_ref")) or str(index)
        if record_id in seen:
            record_id = f"{record_id}#{index}"
        seen.add(record_id)
        pair = coords.parse_pair(record.get("latitude"), record.get("longitude"))
        parsed = dates.parse_date(_date_value(record.get("date_loss")))
        has_coords = pair is not None
        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": _text(record.get("vesselname")) or None,
                "ship_type": _text(record.get("vesseltype")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": pair[0] if has_coords else None,
                "lon": pair[1] if has_coords else None,
                "location_precision": "surveyed" if has_coords else "none",
                "uncertainty_km": 0.1 if has_coords else None,
                "geocode_method": "source_coords" if has_coords else "none",
                "raw": {
                    "latitude": record.get("latitude"),
                    "longitude": record.get("longitude"),
                    "vesselname": record.get("vesselname"),
                    "vesseltype": record.get("vesseltype"),
                    "date_loss": _date_value(record.get("date_loss")),
                    "nms_ref": record.get("nms_ref"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
