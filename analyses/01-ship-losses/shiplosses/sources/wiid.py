"""Ireland Wreck Inventory (WIID) (plan sections 2.3 and 6.2)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..normalize import causes, coords, dates
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "ireland-wiid"

_BOILERPLATE = "we regret that we are unable to supply"


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "ireland-wiid"
    path = directory / "wiid.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="CC-BY-4.0",
        redistribute=True,
        url="https://www.arcgis.com/sharing/rest/content/items/d4b084c880b546fabe38345461b563d2/data",
    )
    frame = pd.read_csv(path, encoding="utf-8-sig", dtype=str, keep_default_na=False)

    rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        record_id = first(record.get("Wreck No")) or str(index)
        name = first(record.get("Wreck Name")) or None
        place = first(record.get("Place of Loss")) or None
        pair = coords.parse_pair(record.get("DD_Lat"), record.get("DD_Long"))
        parsed = dates.parse_date(record.get("Date of Loss")) or dates.parse_date(
            record.get("Date_of_Loss_Year_Only")
        )
        description = first(record.get("Description"))
        if _BOILERPLATE in description.casefold():
            cause_raw = None
            cause = causes.classify("")
        else:
            cause_raw = description or None
            cause = causes.classify(description)

        if pair:
            location_precision, uncertainty, method = "reported", 5.0, "source_coords"
            lat, lon = pair
        elif place:
            location_precision, uncertainty, method = "place", 10.0, "none"
            lat, lon = None, None
        else:
            location_precision, uncertainty, method = "none", None, "none"
            lat, lon = None, None

        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": name,
                "ship_type": first(record.get("Classification")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": lat,
                "lon": lon,
                "location_text": place,
                "location_precision": location_precision,
                "uncertainty_km": uncertainty,
                "geocode_method": method,
                "cause_raw": cause_raw,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "raw": {
                    "Wreck Name": record.get("Wreck Name"),
                    "Wreck No": record.get("Wreck No"),
                    "Classification": record.get("Classification"),
                    "Place of Loss": record.get("Place of Loss"),
                    "Date of Loss": record.get("Date of Loss"),
                    "DD_Lat": record.get("DD_Lat"),
                    "DD_Long": record.get("DD_Long"),
                    "Description": record.get("Description"),
                    "Date_of_Loss_Year_Only": record.get("Date_of_Loss_Year_Only"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
