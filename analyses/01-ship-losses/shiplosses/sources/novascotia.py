"""Nova Scotia shipwrecks (plan section 2.3)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..normalize import causes, dates
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "novascotia-shipwrecks"

_NAME_SUFFIX = re.compile(r"\s*[-\u2013\u2014]\s*1[4-9]\d\d\s*$")
_NON_LOSS_EVENTS = {"damaged", "dismasted", "loss of spars", "strained", "serious damage"}


def _ship_name(raw: object) -> str | None:
    text = first(raw).replace("\xa0", " ")
    text = _NAME_SUFFIX.sub("", text).strip()
    return text or None


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "novascotia-shipwrecks"
    path = directory / "novascotia-shipwrecks.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="NS-Open-Government-Licence",
        redistribute=True,
        url="https://data.novascotia.ca/api/views/rq3a-h5hk/rows.csv?accessType=DOWNLOAD",
    )
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)

    rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        event = first(record.get("Event"))
        cause = causes.classify(event)
        is_total_loss = cause.is_total_loss and event.casefold() not in _NON_LOSS_EVENTS
        parsed = dates.parse_date(record.get("Date of Wreck"))
        place = first(record.get("Location of wreck")) or None

        rows.append(
            {
                "source": meta["source"],
                "source_record_id": str(index),
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": _ship_name(record.get("Vessel Name")),
                "ship_type": first(record.get("Vessel Type")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "location_text": place,
                "location_precision": "place" if place else "none",
                "uncertainty_km": 10.0 if place else None,
                "cause_raw": event or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": is_total_loss,
                "route_from": first(record.get("Voyage from")) or None,
                "route_to": first(record.get("Voyage To")) or None,
                "raw": {
                    "Vessel Name": record.get("Vessel Name"),
                    "Date of Wreck": record.get("Date of Wreck"),
                    "Event": record.get("Event"),
                    "Location of wreck": record.get("Location of wreck"),
                    "Voyage from": record.get("Voyage from"),
                    "Voyage To": record.get("Voyage To"),
                    "Built At": record.get("Built At"),
                    "Vessel Type": record.get("Vessel Type"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
