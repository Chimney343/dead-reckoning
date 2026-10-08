"""Cause classification from free text (plan section 5.4).

Rules live in ``data/cause_rules.csv`` and are evaluated in ascending
``priority`` order; the first match wins. ``weather_related`` is detected
independently of the chosen class.
"""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

_CSV = Path(__file__).resolve().parents[2] / "data" / "cause_rules.csv"
_WEATHER = re.compile(
    r"storm|hurricane|typhoon|cyclone|gale|tempest|squall|\bice\b|weather", re.IGNORECASE
)


@dataclass(frozen=True)
class CauseResult:
    cause_class: str
    weather_related: bool
    is_total_loss: bool


@lru_cache(maxsize=1)
def _rules() -> list[tuple[int, re.Pattern[str], str, bool]]:
    rules: list[tuple[int, re.Pattern[str], str, bool]] = []
    with _CSV.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            regex = row.get("regex", "").strip()
            if not regex:
                continue
            is_total = str(row.get("is_total_loss", "true")).strip().casefold() in {
                "true",
                "1",
                "yes",
            }
            rules.append(
                (
                    int(row["priority"]),
                    re.compile(regex, re.IGNORECASE),
                    row["cause_class"].strip(),
                    is_total,
                )
            )
    rules.sort(key=lambda item: item[0])
    return rules


def _text(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def classify(text: object) -> CauseResult:
    """Classify a cause phrase into one of the eight classes."""
    source = _text(text)
    weather = bool(_WEATHER.search(source))
    for _priority, regex, cause_class, is_total in _rules():
        if regex.search(source):
            return CauseResult(cause_class, weather, is_total)
    return CauseResult("unknown", weather, True)
