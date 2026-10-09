"""Layer 1: TDDate parsing for both site formats, plus dimension and gun helpers.

The raw string is always kept; every derived field is None when the input is
absent or malformed.
"""

from __future__ import annotations

import pytest
from threedecks.parsing.dates import (
    parse_dimension,
    parse_guns,
    parse_long_date,
    parse_td_date,
)

# --- D.M.YYYY and partial forms (ship pages) ------------------------------


def test_full_day_month_year():
    d = parse_td_date("22.1.1785")
    assert d.raw == "22.1.1785"
    assert d.iso == "1785-01-22"
    assert d.precision == "day"
    assert d.qualifier is None
    assert d.julian_alt_year is None


def test_month_year_partial():
    d = parse_td_date("4.1788")
    assert d.iso == "1788-04"
    assert d.precision == "month"
    assert d.qualifier is None


def test_year_only():
    d = parse_td_date("1790")
    assert d.iso == "1790"
    assert d.precision == "year"


def test_julian_alternate_year_without_tooltip():
    d = parse_td_date("1.2.1702/03")
    assert d.iso == "1702-02-01"
    assert d.precision == "day"
    assert d.julian_alt_year == 1703
    assert d.gregorian_iso is None


def test_julian_tooltip_gives_gregorian_iso():
    d = parse_td_date(
        "1.2.1702/03",
        tooltip="1st February 1702 (NS 12th February 1703)",
    )
    assert d.tooltip == "1st February 1702 (NS 12th February 1703)"
    assert d.julian_alt_year == 1703
    assert d.gregorian_iso == "1703-02-12"


# --- YYYY/MM/DD forms (captures list) --------------------------------------


def test_slash_full_date():
    d = parse_td_date("1704/04/16")
    assert d.iso == "1704-04-16"
    assert d.precision == "day"


def test_slash_month():
    d = parse_td_date("1718/02")
    assert d.iso == "1718-02"
    assert d.precision == "month"


def test_bef_year():
    d = parse_td_date("bef.1799")
    assert d.raw == "bef.1799"
    assert d.qualifier == "bef."
    assert d.iso == "1799"
    assert d.precision == "year"


def test_bef_month():
    d = parse_td_date("bef.1799/03")
    assert d.qualifier == "bef."
    assert d.iso == "1799-03"
    assert d.precision == "month"


# --- missing and malformed -------------------------------------------------


@pytest.mark.parametrize("raw", ["?", "", "   "])
def test_unknown_keeps_raw_only(raw):
    d = parse_td_date(raw)
    assert d.raw == raw
    assert d.iso is None
    assert d.precision is None
    assert d.qualifier is None


def test_malformed_keeps_raw_only():
    d = parse_td_date("circa autumn")
    assert d.raw == "circa autumn"
    assert d.iso is None
    assert d.precision is None


# --- dimension helper ------------------------------------------------------


def test_dimension_feet_inches():
    assert parse_dimension("190' 0\"") == 190.0


def test_dimension_thousands_separator():
    assert parse_dimension("1,815.5") == 1815.5


def test_dimension_unparseable():
    assert parse_dimension("Unknown") is None


# --- gun-string helper -----------------------------------------------------


def test_guns_with_pounder_unit():
    assert parse_guns("28 Spanish 24-Pounder") == (28, "Spanish", 24, "Pounder")


def test_guns_with_pound_obus():
    assert parse_guns("4 Spanish 32-Pound Obús") == (4, "Spanish", 32, "Pound")


def test_guns_unparseable():
    assert parse_guns("Unknown") is None
    assert parse_guns("74") is None


# --- qualifiers seen in the 2026-10-03 smoke run ----------------------------


@pytest.mark.parametrize(
    "raw,qualifier,iso,alt",
    [
        ("c.18.6.1744", "c.", "1744-06-18", None),
        ("c.1711", "c.", "1711", None),
        ("aft.9.1744", "aft.", "1744-09", None),
        ("aft.15.2.1745/46", "aft.", "1745-02-15", 1746),
    ],
)
def test_circa_and_after_qualifiers(raw, qualifier, iso, alt):
    d = parse_td_date(raw)
    assert (d.raw, d.qualifier, d.iso, d.julian_alt_year) == (raw, qualifier, iso, alt)


@pytest.mark.parametrize(
    "raw,alt",
    [
        ("26.2.1708/9", 1709),  # seen in the overnight crawl
        ("12.3.1703/4", 1704),
        ("1.2.1702/03", 1703),
        ("31.12.1799/0", 1800),
        ("31.12.1799/00", 1800),
        ("1.1.1799/1800", 1800),
        ("3.1709/10", 1710),
    ],
)
def test_julian_alternate_year_of_any_width(raw, alt):
    d = parse_td_date(raw)
    assert d.julian_alt_year == alt
    assert d.precision in ("day", "month")


# --- date forms seen on fleet pages (Task FL1) ------------------------------
#
# Fleet-list dates are often year-only or approximate; the event log uses
# YYYY/MM/DD (with a written-out tooltip) and the base/shp tables use D.M.YYYY.
# Nothing new is needed in dates.py; these pin the forms so a future change
# cannot break fleet parsing silently.


@pytest.mark.parametrize(
    "raw,tooltip,qualifier,iso,precision",
    [
        ("c.1704", None, "c.", "1704", "year"),
        ("2.1501", None, None, "1501-02", "month"),
        ("1798/08/14", "Tuesday 14th of August 1798", None, "1798-08-14", "day"),
        ("14.8.1798", "14th August 1798", None, "1798-08-14", "day"),
    ],
)
def test_fleet_date_forms(raw, tooltip, qualifier, iso, precision):
    d = parse_td_date(raw, tooltip)
    assert d.raw == raw
    assert d.qualifier == qualifier
    assert d.iso == iso
    assert d.precision == precision


def test_fleet_event_tooltip_is_kept_raw():
    d = parse_td_date("1798/08/14", "Tuesday 14th of August 1798")
    assert d.tooltip == "Tuesday 14th of August 1798"


# --- long-form dates in action headers (Task A1) ----------------------------


def test_long_date_full_day():
    start, end = parse_long_date("21st October 1805")
    assert end is None
    assert (start.iso, start.precision) == ("1805-10-21", "day")


def test_long_date_space_before_suffix():
    # The header renders 21<sup>st</sup>, i.e. "21 st October 1805".
    start, _ = parse_long_date("21 st October 1805")
    assert (start.iso, start.precision) == ("1805-10-21", "day")


def test_long_date_day_with_weekday_and_of():
    start, _ = parse_long_date("Tuesday 14th of August 1798")
    assert (start.iso, start.precision) == ("1798-08-14", "day")


def test_long_date_range_with_gregorian_annotations():
    start, end = parse_long_date(
        "22nd May 1563 (1563/05/31 NS) - 31st July 1563 (1563/08/09 NS)"
    )
    assert (start.iso, start.precision, start.gregorian_iso) == (
        "1563-05-22",
        "day",
        "1563-05-31",
    )
    assert (end.iso, end.precision, end.gregorian_iso) == (
        "1563-07-31",
        "day",
        "1563-08-09",
    )


def test_long_date_month_and_year_precision():
    month, _ = parse_long_date("May 1576")
    assert (month.iso, month.precision) == ("1576-05", "month")
    year, _ = parse_long_date("1801")
    assert (year.iso, year.precision) == ("1801", "year")


def test_long_date_empty_and_unparseable():
    assert parse_long_date("") == (None, None)
    start, end = parse_long_date("sometime")
    assert start.raw == "sometime"
    assert start.precision is None
    assert end is None
