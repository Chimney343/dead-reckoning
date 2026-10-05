"""Wikidata ships and battles (plan sections 2.3 and 4; optional Phase 0.4).

The harvester writes a battle gazetteer and (optionally) ship items with loss
events. This extractor reads ``data/raw/wikidata/ship_losses.csv`` when the
optional query has been run; otherwise it contributes nothing. Battle
coordinates feed the geocoder through ``data/battles.csv``.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from ..normalize import causes, coords, dates, polities
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "wikidata"

EXPECTED = {"ship_name", "date", "lat", "lon"}


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "wikidata"
    path = directory / "ship_losses.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())
    meta = load_meta(directory, ID, tier="T3", licence="CC0-1.0", redistribute=True)
    frame = pd.read_csv(path, dtype=str, keep_default_na=False)
    if not EXPECTED <= set(frame.columns):
        return Extract(empty_losses(), empty_events())

    rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        record_id = first(record.get("qid")) or str(index)
        parsed = dates.parse_date(record.get("date"))
        pair = coords.parse_pair(record.get("lat"), record.get("lon"))
        flag = first(record.get("flag")) or None
        polity = polities.lookup(flag) if flag else None
        cause = causes.classify(record.get("cause"))
        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": first(record.get("ship_name")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": pair[0] if pair else None,
                "lon": pair[1] if pair else None,
                "location_precision": "reported" if pair else "none",
                "uncertainty_km": 5.0 if pair else None,
                "geocode_method": "source_coords" if pair else "none",
                "origin_polity": polity[0] if polity else None,
                "origin_basis": "flag_assumed" if polity else None,
                "flag_at_loss_raw": flag,
                "flag_at_loss_polity": polity[0] if polity else None,
                "cause_raw": first(record.get("cause")) or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "raw": record,
            }
        )
    return Extract(losses=losses_frame(rows), events=empty_events())
