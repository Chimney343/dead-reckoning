"""Layer 1: TDDate parsing for both site formats, plus dimension and gun helpers.

The raw string is always kept; every derived field is None when the input is
absent or malformed.
"""

from __future__ import annotations

import pytest
from threedecks.parsing.dates import parse_dimension, parse_guns, parse_td_date

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
