"""Dutch-Asiatic Shipping voyages (plan sections 2.3 and 6.2)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd

from ..normalize import causes, dates, places, polities
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "dutch-asiatic-shipping"

_LOSS = re.compile(
    r"wrecked|lost|sunk|foundered|burnt|fire|stranded|destroyed|abandoned|missing",
    re.IGNORECASE,
)
_SENTENCE = re.compile(r"(?<=[.;])\s+")
_TRAILING_DATE = re.compile(r"\d{1,2}-\d{1,2}-\d{4}")


def _loss_text(particulars: str) -> str:
    sentences = [part for part in _SENTENCE.split(particulars) if _LOSS.search(part)]
    return " ".join(sentences).strip() or particulars


def _first_date(text: str):
    match = _TRAILING_DATE.search(text)
    if not match:
        return None
    return dates.parse_date(match.group(0))


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "dutch-asiatic-shipping"
    path = directory / "voyages_with_details.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="None stated",
        redistribute=False,
        url="https://resources.huygens.knaw.nl/das/voyages_with_details.csv",
    )
    frame = pd.read_csv(
        path, sep=";", dtype=str, keep_default_na=False, encoding="utf-8"
    )

    rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        particulars = first(record.get("Particulars"))
        if not _LOSS.search(particulars):
            continue
        record_id = first(record.get("Number")) or str(index)
        cause_raw = _loss_text(particulars)
        cause = causes.classify(cause_raw)
        parsed = _first_date(cause_raw) or _first_date(particulars)
        phrase = places.extract_place(particulars)
        built = dates.parse_date(first(record.get("Built")))
        chamber = first(record.get("Chamber"))
        owner = "VOC" + (f" {chamber}" if chamber else "")
        polity = polities.lookup("Dutch Republic")

        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": first(record.get("Name of ship")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "location_text": phrase,
                "location_precision": "place" if phrase else "none",
                "uncertainty_km": 10.0 if phrase else None,
                "origin_raw": "Dutch Republic",
                "origin_polity": polity[0] if polity else None,
                "origin_basis": "flag_assumed",
                "flag_at_loss_raw": "Dutch Republic",
                "flag_at_loss_polity": polity[0] if polity else None,
                "owner_at_loss": owner,
                "cause_raw": cause_raw or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "route_from": first(record.get("Place of departure")) or None,
                "route_to": first(record.get("Place of arrival")) or None,
                "raw": {
                    "Number": record.get("Number"),
                    "Name of ship": record.get("Name of ship"),
                    "Chamber": record.get("Chamber"),
                    "Particulars": record.get("Particulars"),
                    "Date of departure": record.get("Date of departure"),
                    "Place of departure": record.get("Place of departure"),
                    "Place of arrival": record.get("Place of arrival"),
                    "Built": record.get("Built"),
                    "built_year": built.year if built else None,
                    "Yard": record.get("Yard"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
