"""Raw polity values to (polity, polity_group) (plan section 5.3)."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).resolve().parents[2] / "data" / "polities.csv"


@lru_cache(maxsize=1)
def _table() -> dict[tuple[str, str], tuple[str, str]]:
    table: dict[tuple[str, str], tuple[str, str]] = {}
    with _CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("raw_value") or "").strip()
            if not raw:
                continue
            source = (row.get("source") or "*").strip() or "*"
            key = (source, raw.casefold())
            table.setdefault(key, (row["polity"].strip(), row["polity_group"].strip()))
    return table


def lookup(raw: object, source: str = "*") -> tuple[str, str] | None:
    """Return ``(polity, polity_group)`` for a raw value, or ``None``."""
    if raw is None:
        return None
    key = str(raw).strip().casefold()
    if not key:
        return None
    table = _table()
    return table.get((source, key)) or table.get(("*", key))
