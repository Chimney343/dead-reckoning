"""Layer 2 and 3: the ship-page parser.

Synthetic fixtures reproduce each markup quirk from Plan 3.2-3.4. Golden tests
run only when ``tests/fixtures/real/`` is present (gitignored) and pin the real
values from Plan section 6.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.ship_page import is_not_found_page, parse_ship

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
REAL = Path(__file__).parent / "fixtures" / "real"
URL = "https://threedecks.org/index.php?display_type=show_ship&id=1234"


def load(path, name):
    return Selector((path / name).read_text(encoding="utf-8"))


@pytest.fixture
def full():
    return parse_ship(load(SYNTHETIC, "ship_full.html"), URL)


# --- synthetic quirk coverage --------------------------------------------


def test_name_and_id(full):
    assert full.name == "Test Ship"
    assert full.td_id == 1234


def test_base_rows_are_lossless(full):
    assert len(full.base_rows) == 17
    guns = next(r for r in full.base_rows if r.label == "Nominal Guns")
    assert guns.text == "74"
    assert guns.source_code == "B006"


def test_typed_fields(full):
    assert full.nation_id == 7
    assert full.nation_name == "Spain"
    assert full.operator == "Armada Real"
    assert full.class_id == 739
    assert full.ship_type_id == 1
    assert full.ship_type == "Ship of the Line"
    assert full.rig == "Ship Rigged"
    assert full.category == "Third Rate"


def test_nested_shipyard_anchors_are_all_kept(full):
    assert [link.id for link in full.shipyards] == [284, 1947]


def test_designers_and_constructors(full):
    assert [link.id for link in full.designers] == [23686]
    assert [link.id for link in full.constructors] == [23687]


def test_incarnation_links(full):
    assert full.previous_td_ids == [50]
    assert full.next_td_ids == [60]


def test_sidebar_shiplinks_do_not_leak(full):
    assert 9999 not in full.previous_td_ids
    assert 7777 not in full.next_td_ids
    assert 8888 not in full.history[0].ship_ids


def test_lifecycle_dates(full):
    by_label = {item.label: item.date for item in full.lifecycle}
    assert by_label["Launched"].iso == "1785-01-22"
    assert by_label["Captured"].iso == "1805-10-21"
    assert by_label["Sold"].iso == "1816-01-08"
    assert by_label["Ordered"].julian_alt_year == 1703


def test_dimension_sets_by_source(full):
    assert [d.source_code for d in full.dimensions] == ["B006", "AGMAB"]
    assert full.dimensions[0].rows[0][1] == "190' 0\""


def test_armament_sets_survive_td_inside_span(full):
    assert [a.date for a in full.armament] == ["22.1.1785", "21.10.1805"]
    assert full.armament[0].source_code == "SWoA"
    assert "28 Spanish 24-Pounder" in " ".join(full.armament[0].rows[0])


def test_complement(full):
    assert full.complement[0].source_code == "3DECKS"
    assert full.complement[0].rows[0][1] == "505"


def test_history_links_and_source(full):
    assert len(full.history) == 2
    event = full.history[0]
    assert event.date.iso == "1805-10-21"
    assert event.battle_ids == [157]
    assert event.ship_ids == [123]
    assert event.source_code == "B006"
    assert "Trafalgar" in event.text


def test_officers(full):
    commanders = [o for o in full.officers if o.section == "2 Ship Commanders"]
    assert len(commanders) == 2
    assert commanders[0].crewman_id == 23686
    assert commanders[0].rank == "Capitán de navío"
    assert commanders[0].from_date.iso == "1785-03"
    assert commanders[0].source == "B006"


def test_sources(full):
    assert [s.code for s in full.sources] == ["B006", "AGMAB"]
    assert full.sources[0].source_id == 130
    assert full.sources[0].authors == ["J Ignacio González-Aller"]
    assert full.sources[0].type == "Book"


def test_notes(full):
    assert "test note" in full.notes


def test_unknown_and_known_sections(full):
    assert full.unknown_sections == []
    assert full.unknown_labels == ["Refloated By"]


def test_minimal_page_has_no_armament():
    record = parse_ship(load(SYNTHETIC, "ship_minimal.html"), "https://x/1")
    assert record.name == "Minimal Ship"
    assert record.armament == []
    assert record.previous_td_ids == [2744]
    assert record.nation_id == 1


# --- not-found signature ---------------------------------------------------


def test_not_found_page():
    assert is_not_found_page(load(SYNTHETIC, "notfound.html")) is True
    assert is_not_found_page(load(SYNTHETIC, "ship_full.html")) is False


# --- golden tests on real pages (skipped without fixtures) -----------------

requires_real = pytest.mark.skipif(
    not REAL.exists(), reason="tests/fixtures/real/ is absent (run scripts/fetch_fixtures.py)"
)


@requires_real
@pytest.mark.real_pages
def test_golden_2682():
    record = parse_ship(load(REAL, "ship_2682.html"), URL)
    assert len(record.base_rows) == 16
    assert record.nation_id == 7
    dates = {item.label: item.date for item in record.lifecycle}
    assert dates["Launched"].iso == "1785-01-22"
    assert dates["Captured"].iso == "1805-10-21"
    assert record.class_id == 739
    assert [link.id for link in record.shipyards] == [284, 1947]
    assert [d.source_code for d in record.dimensions] == ["B006", "AGMAB", "SWoA"]
    assert len(record.armament) == 3
    assert len(record.history) == 83
    assert len(record.sources) == 7
    assert sum(1 for o in record.officers if o.section == "15 Ship Commanders") == 15
    battle = [e for e in record.history if 157 in e.battle_ids]
    assert battle and battle[0].date.iso == "1805-10-21"
    assert record.unknown_sections == []


@requires_real
@pytest.mark.real_pages
def test_golden_2744():
    record = parse_ship(load(REAL, "ship_2744.html"), URL)
    assert record.next_td_ids == [6358]
    dates = {item.label: item.date for item in record.lifecycle}
    assert dates["Captured"].iso == "1805-10-22"
    assert record.unknown_sections == []


@requires_real
@pytest.mark.real_pages
def test_golden_6358():
    record = parse_ship(load(REAL, "ship_6358.html"), URL)
    assert record.previous_td_ids == [2744]
    assert record.nation_id == 1
    assert record.armament == []
    dates = {item.label: item.date for item in record.lifecycle}
    assert dates["Sold"].iso == "1816-01-08"
    assert record.unknown_sections == []
