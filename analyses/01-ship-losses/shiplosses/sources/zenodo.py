"""Zenodo shipWrecks.csv (plan section 2.2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..normalize import causes, coords, dates, places, polities
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "zenodo-shipwrecks"


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "zenodo-shipwrecks"
    path = directory / "shipWrecks.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T3",
        licence="CC-BY-4.0",
        redistribute=True,
        url="https://zenodo.org/api/records/7347768",
    )
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)

    rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        record_id = first(record.get("")) or str(index)
        name = first(record.get("SHIP")) or None
        flag = first(record.get("FLAG")) or None
        polity = polities.lookup(flag) if flag else None
        pair = coords.parse_zenodo_coordinates(record.get("COORDINATES"))
        parsed = dates.parse_date(record.get("SUNK DATE"))
        zones = [first(record.get(f"ZONA{n}")) for n in range(1, 5)]
        region_text = ", ".join(zone for zone in zones if zone)
        notes = first(record.get("NOTES"))
        cause = causes.classify(notes)
        place_text = places.extract_place(notes)

        if pair:
            location_precision, uncertainty, method = "reported", 5.0, "source_coords"
        elif region_text:
            location_precision, uncertainty, method = "region", 250.0, "source_region"
        else:
            location_precision, uncertainty, method = "none", None, "none"

        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": name,
                "ship_type": first(record.get("VESSEL TYPE")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": pair[0] if pair else None,
                "lon": pair[1] if pair else None,
                "location_text": region_text or place_text or None,
                "location_precision": location_precision,
                "uncertainty_km": uncertainty,
                "geocode_method": method,
                "origin_raw": None,
                "origin_polity": polity[0] if polity else None,
                "origin_basis": "flag_assumed" if polity else None,
                "flag_at_loss_raw": flag,
                "flag_at_loss_polity": polity[0] if polity else None,
                "owner_at_loss": None,
                "cause_raw": notes or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "raw": {
                    "FLAG": flag,
                    "SUNK DATE": record.get("SUNK DATE"),
                    "COORDINATES": record.get("COORDINATES"),
                    "ZONA": zones,
                    "NOTES": notes,
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
