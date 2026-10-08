"""Pure date and numeric helpers for Three Decks pages.

Two date formats are in use:

* ship pages: ``D.M.YYYY`` with partial forms (``4.1788``, ``1790``) and a
  Julian alternate year (``1.2.1702/03``, meaning 1 Feb 1702 OS = 12 Feb 1703 NS);
* the captures list: ``YYYY/MM/DD``, ``YYYY/MM`` and ``YYYY``.

Either may carry a qualifier: ``bef.`` (before), ``aft.`` (after) or ``c.``
(circa), as in ``c.18.6.1744`` or ``aft.15.2.1745/46``.

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

# The Julian alternate year can be 1 to 4 digits: 1702/03, 1708/9, 1799/1800.
_DAY_DOT = re.compile(r"^(\d{1,2})\.(\d{1,2})\.(\d{4})(?:/(\d{1,4}))?$")
_MONTH_DOT = re.compile(r"^(\d{1,2})\.(\d{4})(?:/(\d{1,4}))?$")
_YEAR = re.compile(r"^(\d{4})$")
_SLASH_DMY = re.compile(r"^(\d{4})/(\d{1,2})/(\d{1,2})$")
_SLASH_MY = re.compile(r"^(\d{4})/(\d{1,2})$")
_QUALIFIER = re.compile(r"^(bef\.?|aft\.?|c\.)\s*", re.IGNORECASE)
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
    """``1708`` + ``"9"`` -> 1709; the digits replace the year's last ones,
    rolling over when the result is not later (``1799`` + ``"0"`` -> 1800)."""
    if alt is None:
        return None
    if len(alt) >= 4:
        return int(alt)
    value = int(str(year)[: -len(alt)] + alt)
    return value if value > year else value + 10 ** len(alt)


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

    match = _QUALIFIER.match(work)
    if match:
        result.qualifier = match.group(1).lower().rstrip(".") + "."
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


# --- long-form dates in action headers (Task A1) ---------------------------
#
# An action header writes the date out in full: "21st October 1805", or a range
# "22nd May 1563 (1563/05/31 NS) - 31st July 1563 (1563/08/09 NS)". The Julian
# alternate is given in a trailing "(YYYY/MM/DD NS)" parenthetical.

_MONTH_NAMES = "|".join(_MONTHS)
_LONG_DAY = re.compile(
    rf"(\d{{1,2}})\s*(?:st|nd|rd|th)?\s+(?:of\s+)?({_MONTH_NAMES})\s+(\d{{4}})",
    re.IGNORECASE,
)
_LONG_MONTH = re.compile(rf"({_MONTH_NAMES})\s+(\d{{4}})", re.IGNORECASE)
_LONG_YEAR = re.compile(r"(\d{4})")
_LONG_WEEKDAY = re.compile(
    r"^(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\s+", re.IGNORECASE
)
_NS_PAREN = re.compile(r"\(\s*(\d{4})/(\d{1,2})/(\d{1,2})\s+NS\s*\)")


def _ws(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _split_long_date(text: str) -> tuple[str, str | None] | None:
    """Split on ``" - "`` at the top parenthesis level; None for empty text."""
    text = _ws(text)
    if not text:
        return None
    depth = 0
    for i, char in enumerate(text):
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and text.startswith(" - ", i):
            return text[:i], text[i + 3 :]
    return text, None


def _parse_long_part(part: str) -> TDDate:
    part = _ws(part)
    result = TDDate(raw=part)
    ns = _NS_PAREN.search(part)
    if ns:
        result.gregorian_iso = f"{int(ns[1]):04d}-{int(ns[2]):02d}-{int(ns[3]):02d}"
    work = _LONG_WEEKDAY.sub("", _NS_PAREN.sub("", part).strip())

    if (m := _LONG_DAY.search(work)) is not None:
        day, month = int(m[1]), _MONTHS[m[2].lower()]
        if 1 <= day <= 31:
            result.iso = f"{int(m[3]):04d}-{month:02d}-{day:02d}"
            result.precision = "day"
        return result

    if (m := _LONG_MONTH.search(work)) is not None:
        month = _MONTHS[m[1].lower()]
        result.iso = f"{int(m[2]):04d}-{month:02d}"
        result.precision = "month"
        return result

    if (m := _LONG_YEAR.search(work)) is not None:
        result.iso = m[1]
        result.precision = "year"
        return result

    return result


def parse_long_date(text: str) -> tuple[TDDate | None, TDDate | None]:
    """Parse a written-out action date (and optional range) into TDDates.

    Returns ``(start, end)``; ``end`` is None for a single date and both are None
    for empty text. An unparseable part is kept as ``TDDate(raw=part)`` with no
    precision, so nothing is ever silently dropped.
    """
    split = _split_long_date(text)
    if split is None:
        return None, None
    start_text, end_text = split
    start = _parse_long_part(start_text)
    end = _parse_long_part(end_text) if end_text else None
    return start, end


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
