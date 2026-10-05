"""EMODnet Heritage Shipwrecks (plan section 2.3)."""

from __future__ import annotations

import json
from pathlib import Path

from ..normalize import causes, coords, dates
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import load_meta, losses_frame

ID = "emodnet-shipwrecks"


def _null(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text.casefold() == "n/a":
        return None
    return text


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "emodnet-shipwrecks"
    path = directory / "emodnet-shipwrecks.geojson"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="CC-BY-4.0",
        redistribute=True,
        url="https://ows.emodnet-humanactivities.eu/",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    rows: list[dict] = []
    for index, feature in enumerate(payload.get("features", [])):
        props = feature.get("properties") or {}
        record_id = _null(props.get("source_id")) or str(index)
        name = _null(props.get("name"))
        context = _null(props.get("sink_context"))
        cause = causes.classify(context or "")
        parsed = dates.parse_date(_null(props.get("sink_yr")))

        pair = None
        geometry = feature.get("geometry") or {}
        coordinates = geometry.get("coordinates")
        if isinstance(coordinates, (list, tuple)) and len(coordinates) >= 2:
            try:
                lon, lat = float(coordinates[0]), float(coordinates[1])
            except (TypeError, ValueError):
                lon = lat = None
            if coords.valid(lat, lon):
                pair = (lat, lon)

        if pair:
            location_precision, uncertainty, method = "reported", 5.0, "source_coords"
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
                "ship_type": _null(props.get("obj_type")),
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": pair[0] if pair else None,
                "lon": pair[1] if pair else None,
                "location_precision": location_precision,
                "uncertainty_km": uncertainty,
                "geocode_method": method,
                "cause_raw": context,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "route_from": _null(props.get("place_orig")),
                "route_to": _null(props.get("place_dest")),
                "raw": {
                    "source_id": props.get("source_id"),
                    "name": props.get("name"),
                    "country": props.get("country"),
                    "sink_context": props.get("sink_context"),
                    "sink_yr": props.get("sink_yr"),
                    "obj_type": props.get("obj_type"),
                    "place_orig": props.get("place_orig"),
                    "place_dest": props.get("place_dest"),
                    "source_inf": props.get("source_inf"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
