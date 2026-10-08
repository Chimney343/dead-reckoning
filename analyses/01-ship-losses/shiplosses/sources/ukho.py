"""UKHO wrecks and obstructions, read from the quoted TSV in the extra export.

The DBF in the shapefile cuts ``circumstances_of_loss`` at 254 characters, so
the TSV is the canonical source (plan sections 2.2 and 5).
"""

from __future__ import annotations

import io
import re
import zipfile
from pathlib import Path

import pandas as pd

from ..normalize import causes, coords, dates, polities
from ..normalize.names import normalize_name
from ..schema import empty_events, empty_losses, event_row
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "ukho-wrecks"

_OWNER = re.compile(r"OWNED AT TIME OF LOSS BY\s+([^.]*)", re.IGNORECASE)
_BUILT = re.compile(r"BUILT IN\s+(\d{3,4})?\s*(?:BY\s+)?([^.]*)", re.IGNORECASE)
_EX = re.compile(r"\bEX-([A-Z][A-Z0-9 '\-]*?)(?:\s+\d{2})?(?:[.,;]|$)", re.IGNORECASE)


def _circumstances(text: str) -> tuple[str | None, list[str], str | None]:
    """Return ``(owner, former_names, build_phrase)`` from lost circumstances."""
    if not text:
        return None, [], None
    owner_match = _OWNER.search(text)
    owner = owner_match.group(1).strip(" .;,") or None if owner_match else None
    former = []
    for match in _EX.findall(text):
        name = re.sub(r"\s*'?\d{2}\s*$", "", match).strip(" .;,")
        if name:
            former.append(name)
    built_match = _BUILT.search(text)
    built = None
    if built_match:
        parts = [part for part in built_match.groups() if part and part.strip()]
        built = " ".join(part.strip() for part in parts) or None
    return owner, former, built


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "ukho-wrecks" / "extra"
    archive = directory / "ukho-wrecks-extra.zip"
    if not archive.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="OGL",
        redistribute=True,
        url="https://datahub.admiralty.co.uk/",
    )
    with zipfile.ZipFile(archive) as bundle:
        raw_bytes = bundle.read("Wrecks.txt")

    frame = pd.read_csv(
        io.BytesIO(raw_bytes),
        sep="\t",
        quotechar='"',
        dtype=str,
        keep_default_na=False,
        na_filter=False,
    )
    is_obstruction = frame["obstruction_category"].str.strip() != ""
    is_wreck = frame["wreck_category"].str.strip() != ""
    frame = frame[~(is_obstruction & ~is_wreck)]

    rows: list[dict] = []
    events: list[dict] = []
    seen_events: set[str] = set()
    id_counts: dict[str, int] = {}
    for record in frame.to_dict("records"):
        record_id = first(record.get("wreck_id"))
        if not record_id:
            continue
        id_counts[record_id] = id_counts.get(record_id, 0) + 1
        if id_counts[record_id] > 1:
            record_id = f"{record_id}:{id_counts[record_id]}"
        lat = coords.parse_degrees_minutes(record.get("latitude"))
        lon = coords.parse_degrees_minutes(record.get("longitude"))
        parsed = dates.parse_date(record.get("date_sunk")) or dates.parse_date(
            record.get("reported_year")
        )
        flag = first(record.get("flag")) or None
        polity = polities.lookup(flag) if flag else None
        circumstances = first(record.get("circumstances_of_loss"))
        owner, former, built = _circumstances(circumstances)
        cause = causes.classify(circumstances)
        name = first(record.get("name")) or None

        row = {
            "source": meta["source"],
            "source_record_id": record_id,
            "source_url": meta["source_url"],
            "tier": meta["tier"],
            "licence": meta["licence"],
            "redistribute": meta["redistribute"],
            "ship_name": name,
            "former_names": former,
            "ship_type": first(record.get("type")) or None,
            "loss_date": parsed.iso if parsed else None,
            "loss_year": parsed.year if parsed else None,
            "date_precision": parsed.precision if parsed else "none",
            "lat": lat,
            "lon": lon,
            "location_text": first(record.get("position")) or None,
            "location_precision": "surveyed" if lat is not None and lon is not None else "none",
            "uncertainty_km": 0.1 if lat is not None else None,
            "geocode_method": "source_coords" if lat is not None else "none",
            "origin_raw": built,
            "origin_polity": polity[0] if polity else None,
            "origin_basis": "built" if built else ("flag_assumed" if polity else None),
            "flag_at_loss_raw": flag,
            "flag_at_loss_polity": polity[0] if polity else None,
            "owner_at_loss": owner,
            "cause_raw": circumstances or None,
            "cause_class": cause.cause_class,
            "weather_related": cause.weather_related,
            "is_total_loss": cause.is_total_loss,
            "raw": {
                "wreck_category": record.get("wreck_category"),
                "obstruction_category": record.get("obstruction_category"),
                "circumstances_of_loss": circumstances,
                "latitude": record.get("latitude"),
                "longitude": record.get("longitude"),
                "date_sunk": record.get("date_sunk"),
            },
        }
        rows.append(row)
        for former_name in former:
            event_id = f"{record_id}:renamed:{normalize_name(former_name)}"
            if event_id in seen_events:
                continue
            seen_events.add(event_id)
            events.append(
                event_row(
                    source=meta["source"],
                    source_record_id=event_id,
                    ship_name=former_name,
                    mechanism="renamed",
                    to_polity=polity[0] if polity else None,
                    raw={"from": name, "circumstances": circumstances},
                )
            )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(),
        events=pd.DataFrame(events) if events else empty_events(),
    )
