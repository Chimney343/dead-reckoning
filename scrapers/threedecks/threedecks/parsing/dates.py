"""Pure date and numeric helpers for Three Decks pages.

Two date formats are in use:

* ship pages: ``D.M.YYYY`` with partial forms (``4.1788``, ``1790``) and a
  Julian alternate year (``1.2.1702/03``, meaning 1 Feb 1702 OS = 12 Feb 1703 NS);
* the captures list: ``YYYY/MM/DD``, ``YYYY/MM`` and ``YYYY``, with an
  optional ``bef.`` qualifier.

A date is never reconciled: the raw string is always kept, and any field that
cannot be derived stays ``None``.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_MONTHS = {
    "january": 1,
    "february": 2,
    "march": 3,
    "april": 4,
    "may": 5,
    "june": 6,
    "july": 7,
    "august": 8,
    "september": 9,
    "october": 10,
    "november": 11,
    "december": 12,
}

_DAY_DOT = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:/(\d{2}|\d{4}))?$")
_MONTH_DOT = re.compile(r"^(\d{1,2})\.(\d{4})(?:/(\d{2}|\d{4}))?$")
_YEAR = re.compile(r"^(\d{4})$")
_SLASH_DMY = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_SLASH_MY = re.compile(r"^(\d{4})/(\d{1,2})$")
_BEF = re.compile(r"^bef\.?\s*", re.IGNORECASE)
_NS = re.compile(r"NS\s+(\d{1,2})(?:st|nd|rd|th)?\s+([A-Za-z]+)\s+(\d{4})")


@dataclass
class TDDate:
    """A parsed Three Decks date. ``raw`` is always preserved."""

    raw: str
    iso: str | None = None
    precision: str | None = None
    qualifier: str | None = None
    julian_alt_year: int | None = None
    tooltip: str | None = None
    gregorian_iso: str | None = None


def _alt_year(year: int, alt: str | None) -> int | None:
    if alt is None:
        return None
    value = int(alt)
    if value < 100:
        value += (year // 100) * 100
    return value


def _gregorian_from_tooltip(tooltip: str | None) -> str | None:
    if not tooltip:
        return None
    match = _NS.search(tooltip)
    if not match:
        return None
    day, month_name, year = match.groups()
    month = _MONTHS.get(month_name.lower())
    if month is None:
        return None
    return f"{int(year):04d}-{month:02d}-{int(day):02d}"


def parse_td_date(raw: str, tooltip: str | None = None) -> TDDate:
    """Parse a Three Decks date string, keeping the raw value."""
    result = TDDate(raw=raw, tooltip=tooltip, gregorian_iso=_gregorian_from_tooltip(tooltip))
    work = raw.strip()
    if work in ("", "?"):
        return result

    match = _BEF.match(work)
    if match:
        result.qualifier = "bef."
        work = work[match.end() :].strip()

    if (m := _DAY_DOT.match(work)) is not None:
        day, month, year, alt = int(m[1]), int(m[2]), int(m[3]), m[4]
        if 1 <= month <= 12 and 1 <= day <= 31:
            result.iso = f"{year:04d}-{month:02d}-{day:02d}"
            result.precision = "day"
            result.julian_alt_year = _alt_year(year, alt)
        return result

    if (m := _MONTH_DOT.match(work)) is not None:
        month, year, alt = int(m[1]), int(m[2]), m[3]
        if 1 <= month <= 12:
            result.iso = f"{year:04d}-{month:02d}"
            result.precision = "month"
            result.julian_alt_year = _alt_year(year, alt)
        return result

    if (m := _YEAR.match(work)) is not None:
        result.iso = m[1]
        result.precision = "year"
        return result

    if (m := _SLASH_DMY.match(work)) is not None:
        year, month, day = m[1], int(m[2]), int(m[3])
        if 1 <= month <= 12 and 1 <= day <= 31:
            result.iso = f"{year}-{month:02d}-{day:02d}"
            result.precision = "day"
        return result

    if (m := _SLASH_MY.match(work)) is not None:
        year, month = m[1], int(m[2])
        if 1 <= month <= 12:
            result.iso = f"{year}-{month:02d}"
            result.precision = "month"
        return result

    return result


_FEET_INCHES = re.compile(r"^\s*([\d,]+)'\s*(?:([\d.]+)\s*\"?)?")
_PLAIN_NUMBER = re.compile(r"^\s*([\d,]+(?:\.\d+)?)\s*$")
_GUNS = re.compile(r"^\s*(\d+)\s+([^\d\s]+)\s+(\d+)-([A-Za-zÀ-ÿ]+)")


def parse_dimension(text: str) -> float | None:
    """Parse a dimension such as ``190' 0"`` or ``1,815.5`` into a number.

    The unit is ignored: the column's label carries it. Raw values stay on the
    record; this is a typed convenience.
    """
    match = _FEET_INCHES.match(text)
    if match and (match[1] or match[1] == "0"):
        feet = float(match[1].replace(",", ""))
        inches = float(match[2]) if match[2] else 0.0
        return feet + inches / 12.0
    plain = _PLAIN_NUMBER.match(text)
    if plain:
        return float(plain[1].replace(",", ""))
    return None


def parse_guns(text: str) -> tuple[int, str, int, str] | None:
    """Parse ``28 Spanish 24-Pounder`` -> ``(28, "Spanish", 24, "Pounder")``.

    Descriptors after the unit (for example ``Obús``) are dropped here; the raw
    string is kept on the record.
    """
    match = _GUNS.match(text)
    if not match:
        return None
    return int(match[1]), match[2], int(match[3]), match[4]
