"""Prize Papers captures and the ships they took (plan section 2.2).

Prize Papers records captures, not sinkings, so each capture becomes an
ownership event. A loss row is emitted only when the capture text explicitly
mentions destruction.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd

from ..normalize import causes, coords, dates, polities
from ..schema import empty_events, empty_losses, event_row
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "prize-papers"

_DESTRUCTION = re.compile(
    r"\b(?:sunk|sunken|sank|scuttled|destroyed|burnt|burned|blown up|blew up)\b",
    re.IGNORECASE,
)


def _scalar(value: object) -> str:
    if isinstance(value, (list, tuple)):
        for item in value:
            text = first(item)
            if text:
                return text
        return ""
    return first(value)


def _geometry_strings(value: object) -> list[str]:
    candidates = value if isinstance(value, list) else [value]
    geometries: list[str] = []
    for candidate in candidates:
        text = first(candidate)
        if not text:
            continue
        try:
            payload = json.loads(text)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("type") == "FeatureCollection":
            for feature in payload.get("features", []):
                geometry = feature.get("geometry")
                if geometry:
                    geometries.append(json.dumps(geometry))
        else:
            geometries.append(text)
    return geometries


def _first_coords(value: object) -> tuple[float, float] | None:
    for text in _geometry_strings(value):
        try:
            pair = coords.geojson_centroid(text)
        except Exception:
            pair = None
        if pair:
            return pair
    return None


def _load_docs(directory: Path, prefix: str) -> dict[str, dict]:
    docs: dict[str, dict] = {}
    for path in sorted(directory.glob(f"{prefix}_*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        for doc in payload.get("docs", []):
            pi = _scalar(doc.get("PI"))
            if pi:
                docs[pi] = doc
    return docs


def _ship_fields(ship: dict | None) -> dict:
    if not ship:
        return {"name": "", "ruling": "", "polity": "", "former": []}
    former = ship.get("MD_SHIP_FORMER_NAMES")
    if isinstance(former, list):
        former_names = [text for text in (first(item) for item in former) if text]
    else:
        single = first(former)
        former_names = [single] if single else []
    name = _scalar(ship.get("MD_SHIP_ALL_NAMES"))
    ruling = _scalar(ship.get("MD_SHIP_RULING_AUTHORITY")) or _scalar(ship.get("MD_SHIP_FLAG"))
    polity = polities.lookup(ruling)
    return {
        "name": name,
        "ruling": ruling,
        "polity": polity[0] if polity else "",
        "former": former_names,
    }


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "prize-papers"
    if not any(directory.glob("ship_*.json")) and not any(directory.glob("capture_*.json")):
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="Metadata terms unstated; images research-only",
        redistribute=False,
        url="https://portal.prizepapers.de/",
    )
    ships = _load_docs(directory, "ship")
    captures = _load_docs(directory, "capture")
    events = _load_docs(directory, "event")

    capture_links: dict[str, list[dict]] = {}
    for event in events.values():
        link = _scalar(event.get("MD_EVENT_CAPTURE_LINK"))
        if link:
            capture_links.setdefault(link, []).append(event)

    loss_rows: list[dict] = []
    event_rows: list[dict] = []
    for index, (pi, capture) in enumerate(sorted(captures.items())):
        parsed = dates.parse_date(_scalar(capture.get("MD_CAPTURE_DATE_CREATED_START")))
        if parsed and parsed.year > 1860:
            continue
        place = _scalar(capture.get("MD_CAPTURE_PLACE"))
        pair = _first_coords(capture.get("MD_ALL_COORDS_FOR_SPATIALSEARCH"))
        if pair:
            location_precision, method = "reported", "source_coords"
        elif place:
            location_precision, method = "place", "none"
        else:
            location_precision, method = "none", "none"
        linked = capture_links.get(pi, [])
        linked_event = linked[0] if linked else {}
        ship_pi = _scalar(linked_event.get("PI_TOPSTRUCT"))
        ship = ships.get(ship_pi)
        ship_info = _ship_fields(ship)
        ship_name = ship_info["name"]
        ruling = ship_info["ruling"]
        polity = ship_info["polity"]
        captor = _scalar(capture.get("MD_CAPTURE_CONFISCATING_ACTOR_UNTOKENIZED"))
        description = _scalar(capture.get("MD_CAPTURE_DESCRIPTION"))
        event_text = " ".join(
            _scalar(value)
            for value in linked_event.values()
            if isinstance(value, str)
        )
        record_id = pi or str(index)
        raw = {
            "PI": pi,
            "PI_TOPSTRUCT": ship_pi,
            "MD_CAPTURE_PLACE": place,
            "MD_CAPTURE_TYPE": _scalar(capture.get("MD_CAPTURE_TYPE")),
            "MD_CAPTURE_DATE_CREATED_START": _scalar(
                capture.get("MD_CAPTURE_DATE_CREATED_START")
            ),
            "MD_EVENT_RULING_AUTHORITY": _scalar(linked_event.get("MD_EVENT_RULING_AUTHORITY")),
            "MD_EVENT_JOURNEY_TYPE": _scalar(linked_event.get("MD_EVENT_JOURNEY_TYPE")),
        }

        event_rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "ship_name": ship_name or None,
                "date": parsed.iso if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "from_polity": polity or None,
                "to_polity": None,
                "mechanism": "captured",
                "captor": captor or None,
                "place_text": place or None,
                "lat": pair[0] if pair else None,
                "lon": pair[1] if pair else None,
                "location_precision": location_precision,
                "raw": raw,
            }
        )

        text = description or event_text
        if text and _DESTRUCTION.search(text):
            cause = causes.classify(text)
            loss_rows.append(
                {
                    "source": meta["source"],
                    "source_record_id": record_id,
                    "source_url": meta["source_url"],
                    "tier": meta["tier"],
                    "licence": meta["licence"],
                    "redistribute": meta["redistribute"],
                    "ship_name": ship_name or None,
                    "former_names": ship_info["former"],
                    "loss_date": parsed.iso if parsed else None,
                    "loss_year": parsed.year if parsed else None,
                    "date_precision": parsed.precision if parsed else "none",
                    "lat": pair[0] if pair else None,
                    "lon": pair[1] if pair else None,
                    "location_text": place or None,
                    "location_precision": location_precision,
                    "uncertainty_km": 5.0 if pair else None,
                    "geocode_method": method,
                    "origin_raw": ruling or None,
                    "origin_polity": polity or None,
                    "origin_basis": "flag_assumed" if polity else None,
                    "flag_at_loss_raw": ruling or None,
                    "flag_at_loss_polity": polity or None,
                    "owner_at_loss": captor or None,
                    "cause_raw": text,
                    "cause_class": cause.cause_class,
                    "weather_related": cause.weather_related,
                    "is_total_loss": cause.is_total_loss,
                    "raw": raw,
                }
            )

    losses = losses_frame(loss_rows) if loss_rows else empty_losses()
    events_frame = (
        pd.DataFrame([event_row(**row) for row in event_rows]) if event_rows else empty_events()
    )
    return Extract(losses=losses, events=events_frame)
