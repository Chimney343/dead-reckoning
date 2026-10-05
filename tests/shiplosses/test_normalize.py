"""Table-driven tests for the normalisers (plan section 5, section 10)."""

from __future__ import annotations

import pytest
from shiplosses.normalize import causes, coords, dates, names, places, polities


# ----------------------------------------------------------------------- dates
@pytest.mark.parametrize(
    "raw, iso, year, precision",
    [
        ("17970214", "1797-02-14", 1797, "day"),
        ("179702", "1797-02", 1797, "month"),
        ("1797", "1797", 1797, "year"),
        ("14/02/1797", "1797-02-14", 1797, "day"),
        ("14-02-1797", "1797-02-14", 1797, "day"),
        ("1797/02/14", "1797-02-14", 1797, "day"),
        ("1797-02-14", "1797-02-14", 1797, "day"),
        ("1853-02-01", "1853-02-01", 1853, "day"),
    ],
)
def test_parse_date_formats(raw, iso, year, precision):
    got = dates.parse_date(raw)
    assert got.iso == iso
    assert got.year == year
    assert got.precision == precision


def test_parse_date_zenodo_placeholder_is_year_precision():
    got = dates.parse_date("01/01/1805")
    assert got.iso == "1805"
    assert got.year == 1805
    assert got.precision == "year"


def test_parse_date_rejects_out_of_range_year():
    assert dates.parse_date("1370") is None
    assert dates.parse_date("2200") is None
    assert dates.parse_date("") is None
    assert dates.parse_date("not a date") is None


def test_parse_date_spanish_months():
    got = dates.parse_date("14 de febrero de 1797")
    assert got.iso == "1797-02-14"
    assert got.precision == "day"


def test_parse_date_slavevoyages_year():
    got = dates.parse_date("1805")
    assert got.iso == "1805"
    assert got.precision == "year"


# ------------------------------------------------------------------ coordinates
def test_parse_ukho_degrees_minutes():
    assert coords.parse_degrees_minutes("5 33.535 S") == pytest.approx(-5.558917, abs=1e-6)
    assert coords.parse_degrees_minutes("110 57.76 E") == pytest.approx(110.962667, abs=1e-6)
    assert coords.parse_degrees_minutes("20 8.397 S") == pytest.approx(-20.13995, abs=1e-5)
    assert coords.parse_degrees_minutes("") is None
    assert coords.parse_degrees_minutes(None) is None


def test_parse_zenodo_coordinates_strips_bom():
    assert coords.parse_zenodo_coordinates("-4.0818;39.72\ufeff") == pytest.approx(
        (-4.0818, 39.72)
    )


def test_parse_pair_wiid_zero_is_null():
    assert coords.parse_pair("0", "0") is None
    assert coords.parse_pair(0, 0) is None
    assert coords.parse_pair("51.5", "-0.1") == pytest.approx((51.5, -0.1))
    assert coords.parse_pair("", "") is None
    assert coords.parse_pair("95", "10") is None


def test_geojson_centroid_single_vertex_and_polygon():
    one = '{"type": "Polygon", "coordinates": [[[10.0, 20.0]]]}'
    assert coords.geojson_centroid(one) == pytest.approx((20.0, 10.0))
    square = '{"type": "Polygon", "coordinates": [[[0,0],[2,0],[2,2],[0,2],[0,0]]]}'
    assert coords.geojson_centroid(square) == pytest.approx((1.0, 1.0))
    assert coords.geojson_centroid("") is None


def test_valid_coordinate():
    assert coords.valid(51.5, -0.1)
    assert not coords.valid(91.0, 0.0)
    assert not coords.valid(0.0, 181.0)
    assert not coords.valid(None, None)


# -------------------------------------------------------------------- names
@pytest.mark.parametrize(
    "raw, expected",
    [
        ("HMS Victory", "victory"),
        ("USS CONSTELLATION", "constellation"),
        ('"Mary" (PROBABLY)', "mary"),
        ("Stronza\u00a0-\u00a01875", "stronza"),
        ("S.S. Great Eastern", "great eastern"),
        ("MV Derbyshire", "derbyshire"),
        ("Caf\u00e9", "cafe"),
    ],
)
def test_normalize_name(raw, expected):
    assert names.normalize_name(raw) == expected


# ------------------------------------------------------------------- polities
def test_map_polity_iso2_and_navies_and_unknown():
    assert polities.lookup("GB") == ("Great Britain", "British")
    assert polities.lookup("FR") == ("France", "French")
    assert polities.lookup("Royal Navy") == ("Great Britain", "British")
    assert polities.lookup("French Navy") == ("France", "French")
    assert polities.lookup("VOC") == ("Dutch Republic", "Dutch")
    assert polities.lookup("Atlantis") is None


# --------------------------------------------------------------------- causes
@pytest.mark.parametrize(
    "text, cause_class, total",
    [
        ("The ship was wrecked near Barmouth.", "stranded", True),
        ("She foundered with all hands", "foundered", True),
        ("Lost in a hurricane", "weather", True),
        ("Caught fire and burnt", "fire_explosion", True),
        ("Sunk in collision with another vessel", "collision", True),
        ("Sunk by the French in action", "enemy_action", True),
        ("Scuttled to avoid capture", "scuttled", True),
        ("Missing, cause unknown", "unknown", True),
        ("Refloated the next day", "unknown", False),
        ("Damaged but brought into port", "unknown", False),
        ("Condemned as unseaworthy and sold", "unknown", False),
        ("Captured by a French privateer", "unknown", False),
        ("Volado por su tripulacion", "fire_explosion", True),
        ("Naufrag\u00f3 cerca de la costa", "stranded", True),
        ("Incendiado para evitar su apresamiento", "scuttled", True),
        ("Hundido por el fuego enemigo", "enemy_action", True),
        ("Wrecked and sunk", "stranded", True),
        ("Struck a reef", "stranded", True),
        ("Ran aground", "stranded", True),
        ("Driven ashore in the night", "stranded", True),
        ("Beached", "stranded", True),
        ("Cast away on the coast", "stranded", True),
        ("She foundered", "foundered", True),
        ("Sank at her moorings", "foundered", True),
        ("Capsized", "foundered", True),
        ("Sprang a leak and sank", "foundered", True),
        ("Swamped by heavy seas", "foundered", True),
        ("Went down", "foundered", True),
        ("Lost in a typhoon", "weather", True),
        ("Crushed by ice", "weather", True),
        ("Foundered in a gale", "foundered", True),
        ("Caught fire", "fire_explosion", True),
        ("Exploded", "fire_explosion", True),
        ("Blew up", "fire_explosion", True),
        ("Burnt at anchor", "fire_explosion", True),
        ("Collision with a steamer", "collision", True),
        ("Run down by a steamer", "collision", True),
        ("Sunk by enemy gunfire", "enemy_action", True),
        ("Mined off the coast", "enemy_action", True),
        ("Torpedoed", "enemy_action", True),
        ("Scuttled", "scuttled", True),
        ("Set on fire to avoid capture", "scuttled", True),
        ("Sunk as a blockship", "scuttled", True),
        ("Missing", "unknown", True),
        ("Abandoned", "unknown", True),
        ("Cause not reported", "unknown", True),
        ("Brought on dry land for display", "unknown", False),
        ("Salvaged and returned to service", "unknown", False),
        ("Broken up", "unknown", False),
        ("Dismasted but repaired", "unknown", False),
    ],
)
def test_classify_cause(text, cause_class, total):
    got = causes.classify(text)
    assert got.cause_class == cause_class
    assert got.is_total_loss is total


def test_weather_related_flagged_separately():
    assert causes.classify("Wrecked in a gale off Yarmouth").weather_related
    assert not causes.classify("Sunk in action").weather_related


def test_cause_priority_enemy_beats_scuttled():
    got = causes.classify("Set on fire to avoid capture, then sunk by enemy gunfire")
    assert got.cause_class == "enemy_action"


# --------------------------------------------------------------------- places
@pytest.mark.parametrize(
    "text, expected",
    [
        (
            "The ship was wrecked near Barmouth, Caernarvonshire, United Kingdom.",
            "near Barmouth, Caernarvonshire, United Kingdom",
        ),
        ("She foundered in a storm", None),
        (
            "Sank off Cape Agulhas on 08-01-1730",
            "off Cape Agulhas",
        ),
        (
            "Lost 5 nautical miles south of Beachy Head",
            "Beachy Head",
        ),
    ],
)
def test_extract_place(text, expected):
    assert places.extract_place(text) == expected
