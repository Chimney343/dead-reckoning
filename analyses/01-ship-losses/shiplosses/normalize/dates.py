"""Partial-date parsing (plan section 5.1).

Returns ISO partial dates (``1797``, ``1797-02``, ``1797-02-14``) with a
precision label. Years outside 1400-2030 are rejected. ``dd/mm/yyyy`` values
with ``01/01`` are treated as year precision, because several sources use that
as a placeholder.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

MIN_YEAR = 1400
MAX_YEAR = 2030

_MONTHS_ES = {
    "enero": 1,
    "febrero": 2,
    "marzo": 3,
    "abril": 4,
    "mayo": 5,
    "junio": 6,
    "julio": 7,
    "agosto": 8,
    "septiembre": 9,
    "setiembre": 9,
    "octubre": 10,
    "noviembre": 11,
    "diciembre": 12,
}


@dataclass(frozen=True)
class DateValue:
    iso: str
    year: int
    precision: str


def _make(year: int, month: int | None = None, day: int | None = None) -> DateValue | None:
    if not (MIN_YEAR <= year <= MAX_YEAR):
        return None
    if month is not None and not 1 <= month <= 12:
        return None
    if day is not None and not 1 <= day <= 31:
        return None
    if month is not None and day is not None:
        return DateValue(f"{year:04d}-{month:02d}-{day:02d}", year, "day")
    if month is not None:
        return DateValue(f"{year:04d}-{month:02d}", year, "month")
    return DateValue(f"{year:04d}", year, "year")


def parse_date(raw: object) -> DateValue | None:
    """Parse the date formats used across the loss sources."""
    if raw is None:
        return None
    text = str(raw).strip()
    if not text or text.casefold() in {"nan", "none", "n/a", "nat", "null"}:
        return None

    match = re.fullmatch(r"(\d{4})(\d{2})(\d{2})", text)
    if match:
        return _make(int(match[1]), int(match[2]), int(match[3]))

    match = re.fullmatch(r"(\d{4})(\d{2})", text)
    if match:
        return _make(int(match[1]), int(match[2]))

    match = re.fullmatch(r"(\d{4})", text)
    if match:
        return _make(int(match[1]))

    match = re.fullmatch(r"(\d{1,2})[./-](\d{1,2})[./-](\d{4})", text)
    if match:
        day, month, year = int(match[1]), int(match[2]), int(match[3])
        if day == 1 and month == 1:
            return _make(year)
        return _make(year, month, day)

    match = re.fullmatch(r"(\d{4})[./-](\d{1,2})[./-](\d{1,2})", text)
    if match:
        return _make(int(match[1]), int(match[2]), int(match[3]))

    match = re.fullmatch(
        r"(\d{1,2})\s+de\s+([a-zA-Z\u00e1\u00e9\u00ed\u00f3\u00fa\u00fc\u00f1]+)\s+de\s+(\d{4})",
        text,
        re.IGNORECASE,
    )
    if match:
        month = _MONTHS_ES.get(match[2].casefold())
        if month:
            return _make(int(match[3]), month, int(match[1]))

    return None
