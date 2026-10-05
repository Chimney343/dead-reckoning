"""Shared loss/ownership schema, defaults and validation (plan section 3)."""

from __future__ import annotations

import json
from typing import Any

import pandas as pd

from .normalize.names import normalize_name

DATE_PRECISIONS = {"day", "month", "year", "decade", "none"}
LOCATION_PRECISIONS = {"surveyed", "reported", "place", "region", "none"}
CAUSE_CLASSES = {
    "stranded",
    "foundered",
    "weather",
    "fire_explosion",
    "collision",
    "enemy_action",
    "scuttled",
    "unknown",
}
ORIGIN_BASES = {"built", "registered", "flag_before_change", "flag_assumed"}
MECHANISMS = {"captured", "condemned", "sold", "renamed"}

LOSS_COLUMNS = [
    "loss_id",
    "source",
    "source_record_id",
    "source_url",
    "tier",
    "ship_name",
    "ship_name_norm",
    "former_names",
    "ship_type",
    "loss_date",
    "loss_year",
    "date_precision",
    "lat",
    "lon",
    "location_text",
    "location_precision",
    "uncertainty_km",
    "geocode_method",
    "origin_raw",
    "origin_polity",
    "origin_basis",
    "flag_at_loss_raw",
    "flag_at_loss_polity",
    "owner_at_loss",
    "ownership_changed",
    "ownership_change",
    "ownership_event_ids",
    "cause_raw",
    "cause_class",
    "weather_related",
    "is_total_loss",
    "route_from",
    "route_to",
    "licence",
    "redistribute",
    "cluster_id",
    "is_primary",
    "raw",
    "lat_from",
    "lon_from",
    "location_text_from",
    "location_precision_from",
    "uncertainty_km_from",
    "geocode_method_from",
    "origin_polity_from",
    "owner_at_loss_from",
    "cause_class_from",
    "loss_date_from",
]

EVENT_COLUMNS = [
    "event_id",
    "source",
    "source_record_id",
    "ship_name",
    "ship_name_norm",
    "date",
    "date_precision",
    "from_polity",
    "to_polity",
    "mechanism",
    "captor",
    "place_text",
    "lat",
    "lon",
    "location_precision",
    "raw",
]

LOSS_DTYPES: dict[str, str] = {
    "loss_year": "Int16",
    "lat": "float64",
    "lon": "float64",
    "uncertainty_km": "float64",
    "ownership_changed": "boolean",
    "weather_related": "boolean",
    "is_total_loss": "boolean",
    "redistribute": "boolean",
    "is_primary": "boolean",
}

EVENT_DTYPES: dict[str, str] = {
    "lat": "float64",
    "lon": "float64",
}


def _as_raw(value: Any) -> str:
    if value is None:
        return "{}"
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, default=str)


def _empty(columns: list[str], dtypes: dict[str, str]) -> pd.DataFrame:
    return pd.DataFrame(
        {column: pd.Series(dtype=dtypes.get(column, object)) for column in columns}
    )


def empty_losses() -> pd.DataFrame:
    return _empty(LOSS_COLUMNS, LOSS_DTYPES)


def empty_events() -> pd.DataFrame:
    return _empty(EVENT_COLUMNS, EVENT_DTYPES)


def loss_row(**values: Any) -> dict[str, Any]:
    """Build a complete loss row with documented defaults."""
    row: dict[str, Any] = {column: None for column in LOSS_COLUMNS}
    row["former_names"] = []
    row["ownership_event_ids"] = []
    row["date_precision"] = "none"
    row["location_precision"] = "none"
    row["cause_class"] = "unknown"
    row["geocode_method"] = "none"
    row["weather_related"] = False
    row["is_total_loss"] = True
    row["redistribute"] = True
    row["raw"] = "{}"
    row.update(values)
    if not row.get("loss_id") and row.get("source") and row.get("source_record_id") is not None:
        row["loss_id"] = f"{row['source']}:{row['source_record_id']}"
    if row.get("ship_name") and not row.get("ship_name_norm"):
        row["ship_name_norm"] = normalize_name(row["ship_name"])
    row["raw"] = _as_raw(row.get("raw"))
    return row


def event_row(**values: Any) -> dict[str, Any]:
    row: dict[str, Any] = {column: None for column in EVENT_COLUMNS}
    row["date_precision"] = "none"
    row["location_precision"] = "none"
    row["raw"] = "{}"
    row.update(values)
    if not row.get("event_id") and row.get("source") and row.get("source_record_id") is not None:
        row["event_id"] = f"{row['source']}:{row['source_record_id']}"
    if row.get("ship_name") and not row.get("ship_name_norm"):
        row["ship_name_norm"] = normalize_name(row["ship_name"])
    row["raw"] = _as_raw(row.get("raw"))
    return row


def _check_enum(df: pd.DataFrame, column: str, allowed: set[str], problems: list[str]) -> None:
    if column not in df.columns:
        return
    values = df[column].dropna()
    bad = sorted({str(value) for value in values if str(value) not in allowed})
    if bad:
        problems.append(f"{column} has invalid values: {bad}")


def validate_losses(df: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    missing = [column for column in LOSS_COLUMNS if column not in df.columns]
    if missing:
        return [f"missing columns: {missing}"]
    if df["loss_id"].duplicated().any():
        problems.append("duplicate loss_id values")
    _check_enum(df, "date_precision", DATE_PRECISIONS, problems)
    _check_enum(df, "location_precision", LOCATION_PRECISIONS, problems)
    _check_enum(df, "cause_class", CAUSE_CLASSES, problems)
    _check_enum(df, "origin_basis", ORIGIN_BASES, problems)
    for column, limit in (("lat", 90.0), ("lon", 180.0)):
        values = pd.to_numeric(df[column], errors="coerce").dropna()
        if (values.abs() > limit).any():
            problems.append(f"{column} has out-of-range values")
    if "is_total_loss" in df.columns and df["is_total_loss"].isna().all() and not df.empty:
        problems.append("is_total_loss is all null")
    return problems


def validate_events(df: pd.DataFrame) -> list[str]:
    problems: list[str] = []
    missing = [column for column in EVENT_COLUMNS if column not in df.columns]
    if missing:
        return [f"missing columns: {missing}"]
    if not df.empty and df["event_id"].duplicated().any():
        problems.append("duplicate event_id values")
    _check_enum(df, "date_precision", DATE_PRECISIONS, problems)
    _check_enum(df, "location_precision", LOCATION_PRECISIONS, problems)
    _check_enum(df, "mechanism", MECHANISMS, problems)
    return problems
