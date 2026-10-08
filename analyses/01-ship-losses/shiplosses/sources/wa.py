"""Western Australia shipwrecks (WAM-002) GeoJSON (plan section 2.2)."""

from __future__ import annotations

import json
from pathlib import Path

from ..normalize import causes, dates, polities
from ..schema import empty_events, empty_losses
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "wa-shipwrecks"

_DROP_CAUSES = {"refloated", "brought on dry land for display"}


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "wa-shipwrecks"
    path = directory / "wa-shipwrecks.geojson"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="CC-BY-4.0",
        redistribute=True,
        url="https://public-services.slip.wa.gov.au/",
    )
    payload = json.loads(path.read_text(encoding="utf-8"))

    rows: list[dict] = []
    for index, feature in enumerate(payload.get("features", [])):
        props = feature.get("properties", {})
        if first(props.get("sunk_code")).casefold() in _DROP_CAUSES:
            continue
        record_id = first(props.get("unique_num")) or str(props.get("oid") or index)
        lat, lon = props.get("lat"), props.get("long")
        try:
            lat_f = float(lat) if lat not in (None, "") else None
            lon_f = float(lon) if lon not in (None, "") else None
        except (TypeError, ValueError):
            lat_f = lon_f = None
        fix = first(props.get("position_i"))
        parsed = dates.parse_date(props.get("when_lost"))
        country = first(props.get("country_bu")) or None
        polity = polities.lookup(country) if country else None
        cause_text = f"{first(props.get('sunk_code'))}. {first(props.get('sinking'))}".strip(" .")
        cause = causes.classify(cause_text)
        built = first(props.get("port_built")) or None
        registered = first(props.get("port_regis")) or None
        has_coords = lat_f is not None and lon_f is not None
        if has_coords and fix:
            location_precision, uncertainty = "surveyed", 0.1
        elif has_coords:
            location_precision, uncertainty = "reported", 5.0
        else:
            location_precision, uncertainty = "none", None

        rows.append(
            {
                "source": meta["source"],
                "source_record_id": record_id,
                "source_url": meta["source_url"],
                "tier": meta["tier"],
                "licence": meta["licence"],
                "redistribute": meta["redistribute"],
                "ship_name": first(props.get("name")) or None,
                "ship_type": first(props.get("type_of_si")) or None,
                "loss_date": parsed.iso if parsed else None,
                "loss_year": parsed.year if parsed else None,
                "date_precision": parsed.precision if parsed else "none",
                "lat": lat_f,
                "lon": lon_f,
                "location_text": first(props.get("where_lost"))
                or first(props.get("region"))
                or None,
                "location_precision": location_precision,
                "uncertainty_km": uncertainty,
                "geocode_method": "source_coords" if has_coords else "none",
                "origin_raw": country,
                "origin_polity": polity[0] if polity else None,
                "origin_basis": "built"
                if built or country
                else ("registered" if registered else None),
                "flag_at_loss_raw": None,
                "flag_at_loss_polity": None,
                "owner_at_loss": first(props.get("owner")) or None,
                "cause_raw": cause_text or None,
                "cause_class": cause.cause_class,
                "weather_related": cause.weather_related,
                "is_total_loss": cause.is_total_loss,
                "route_from": first(props.get("port_from")) or None,
                "route_to": first(props.get("port_to")) or None,
                "raw": {
                    "sunk_code": props.get("sunk_code"),
                    "sinking": props.get("sinking"),
                    "position_i": props.get("position_i"),
                    "port_built": props.get("port_built"),
                    "port_regis": props.get("port_regis"),
                    "when_lost": props.get("when_lost"),
                    "master": props.get("master"),
                },
            }
        )

    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(), events=empty_events()
    )
