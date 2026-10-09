"""Layer 2/3: the fleet-list index and fleet page parsers (fleets plan 3, FL3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.fleets import (
    is_fleet_not_found,
    is_fleet_page,
    is_fleetlist_index_page,
    parse_fleet,
    parse_fleet_index,
)

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
REAL = Path(__file__).parent / "fixtures" / "real"
FLEET_URL = "https://threedecks.org/index.php?display_type=show_fleet&id={id}"

requires_real = pytest.mark.skipif(
    not REAL.exists(), reason="tests/fixtures/real/ is absent (run scripts/fetch_fixtures.py)"
)


def load(path, name):
    return Selector((path / name).read_text(encoding="utf-8"))


@pytest.fixture
def full():
    return parse_fleet(load(SYNTHETIC, "fleet_full.html"), FLEET_URL.format(id=1))


# --- completeness signatures ------------------------------------------------


def test_is_fleet_page():
    assert is_fleet_page(load(SYNTHETIC, "fleet_full.html"))
    assert not is_fleet_page(load(SYNTHETIC, "fleet_truncated.html"))
    assert not is_fleet_page(load(SYNTHETIC, "fleet_notfound.html"))


def test_is_fleet_not_found():
    assert is_fleet_not_found(load(SYNTHETIC, "fleet_notfound.html"))
    assert not is_fleet_not_found(load(SYNTHETIC, "fleet_full.html"))


def test_is_fleetlist_index_page():
    assert is_fleetlist_index_page(load(SYNTHETIC, "fleetlist_index.html"))
    assert not is_fleetlist_index_page(load(SYNTHETIC, "fleet_full.html"))


def test_is_fleetlist_index_page_rejects_a_bare_show_fleetlist_link():
    # show_fleet is a prefix of show_fleetlist, so the signature must match exactly.
    html = (
        "<html><head><title>Fleets</title></head><body><div id='datacol'>"
        "<h1>Fleets</h1>"
        "<a href='index.php?display_type=show_fleetlist'>Fleets</a>"
        "</div><span id='copywrite_message'>Copyright</span></body></html>"
    )
    assert not is_fleetlist_index_page(Selector(text=html))


# --- the fleet-list index ---------------------------------------------------


def test_parse_fleet_index_synthetic():
    rows = parse_fleet_index(load(SYNTHETIC, "fleetlist_index.html"))
    assert len(rows) == 3

    first = rows[0]
    assert first.fleet_id == 132
    assert first.name == "French Fleet sent to the aid of the Venetians"
    assert first.nation_id is None
    assert first.nation_text == "Unknown?"
    assert first.commander_ids == []
    assert first.date_from.raw == "2.1501"
    assert first.date_from.iso == "1501-02"
    assert first.date_to.iso == "1501"
    assert len(first.cells) == 5

    assert rows[1].fleet_id == 69 and rows[1].nation_id == 1
    assert rows[2].fleet_id == 139 and rows[2].nation_id == 7
    assert rows[2].commander_ids == [1]
    assert rows[2].commanders[0].tooltip[0] == "Spanish"


# --- a full fleet page ------------------------------------------------------


def test_full_base_table(full):
    assert full.fleet_id == 1
    assert full.name == "Example Fleet"
    assert full.commander_ids == [4757]
    assert (full.formed.iso, full.formed.precision) == ("1798-08-14", "day")
    assert (full.disbanded.iso, full.disbanded.precision) == ("1798", "year")
    assert full.unknown_labels == ["Odd Label"]
    formed = next(row for row in full.base_rows if row.label == "Fleet Formed")
    assert formed.source_code == "ref:1239"


def test_full_ships_table(full):
    assert len(full.ships) == 2
    orion = full.ships[0]
    assert orion.td_id == 5634
    assert orion.ship_label == "Orion (74)"
    assert orion.ship.tooltip == ["1787-1814", "British 74 Gun", "3rd Rate Ship of the Line"]
    assert (orion.joined.iso, orion.left.iso) == ("1798-08-14", "1798")
    assert orion.commander_ids == [4757]
    assert orion.commander_text == "Sir James Saumarez"
    assert orion.notes == "Fleet disbanded"
    assert len(orion.cells) == 7

    conquerant = full.ships[1]
    assert conquerant.td_id == 5635
    assert conquerant.commander_ids == []
    assert conquerant.commander_text is None
    assert conquerant.notes == "Fleet disbanded"


def test_full_events_table(full):
    assert len(full.events) == 3
    first = full.events[0]
    assert (first.date.iso, first.date.tooltip) == ("1798-08-14", "Tuesday 14th of August 1798")
    assert first.text == "Sailed from Aboukir Bay for Gibraltar and England"

    circa = full.events[1]
    assert (circa.date.raw, circa.date.qualifier) == ("c.1704", "c.")
    assert circa.ship_ids == [32724]

    linked = full.events[2]
    assert linked.ship_ids == [5634]
    assert linked.place_ids == [1740]
    assert linked.battle_ids == [157]
    assert linked.source_code == "ref:1239"


def test_full_introduction_sources_and_sections(full):
    assert full.introduction == "An example fleet introduction."
    assert len(full.sources) == 1
    assert full.sources[0].code == "ref:1239"
    assert full.unknown_sections == []


def test_no_visible_field_carries_hover_text(full):
    fields = [full.name]
    for ship in full.ships:
        fields.extend([ship.ship_label, ship.commander_text or "", ship.notes])
    for event in full.events:
        fields.append(event.text)
    assert not any("Naval Sailor" in field for field in fields)


def test_parse_fleet_not_found_shell():
    record = parse_fleet(load(SYNTHETIC, "fleet_notfound.html"), FLEET_URL.format(id=999999))
    assert record.fleet_id == 999999
    assert record.ships == [] and record.events == []
    assert record.formed is None and record.disbanded is None


# --- golden tests on real pages (skipped without fixtures) -----------------


@requires_real
@pytest.mark.real_pages
def test_golden_fleetlist_index():
    rows = parse_fleet_index(load(REAL, "fleetlist_index.html"))
    assert len(rows) == 146
    ids = [row.fleet_id for row in rows]
    assert len(set(ids)) == 146
    assert min(ids) == 1 and max(ids) == 151

    first = rows[0]
    assert first.fleet_id == 132
    assert first.nation_id is None
    assert first.nation_text == "Unknown?"
    assert first.commander_ids == []
    assert first.date_from.raw == "2.1501"

    spanish = {row.fleet_id for row in rows if row.nation_id == 7}
    assert spanish == {139, 146, 151}


@requires_real
@pytest.mark.real_pages
def test_golden_97_saumarez():
    record = parse_fleet(load(REAL, "fleet_97.html"), FLEET_URL.format(id=97))
    assert is_fleet_page(load(REAL, "fleet_97.html"))
    assert record.name == "Saumarez's Squadron 1798"
    assert record.commander_ids == [4757]
    assert record.formed.iso == "1798-08-14"
    assert (record.disbanded.iso, record.disbanded.precision) == ("1798", "year")
    assert len(record.ships) == 13
    orion = record.ships[0]
    assert orion.ship_label == "Orion (74)"
    assert orion.ship.tooltip == ["1787-1814", "British 74 Gun", "3rd Rate Ship of the Line"]
    assert len(record.events) == 1
    assert record.events[0].place_ids == [1740]
    assert record.events[0].ship_ids == []
    assert len(record.sources) == 1
    assert record.unknown_labels == []
    assert record.unknown_sections == []
    assert len({ship.commander_ids[0] for ship in record.ships if ship.commander_ids}) == 7


@requires_real
@pytest.mark.real_pages
def test_golden_139_enriquez():
    record = parse_fleet(load(REAL, "fleet_139.html"), FLEET_URL.format(id=139))
    assert record.name == "Miguel Enriquez's privateer fleet"
    assert len(record.ships) == 33
    assert len(record.events) == 40
    first = record.events[0]
    assert (first.date.raw, first.date.qualifier) == ("c.1704", "c.")
    assert record.introduction is not None
    assert len(record.sources) == 1
    assert record.unknown_labels == []
    assert record.unknown_sections == []


@requires_real
@pytest.mark.real_pages
def test_golden_not_found_probe():
    sel = load(REAL, "fleet_notfound_probe.html")
    assert is_fleet_not_found(sel)
    assert not is_fleet_page(sel)


@requires_real
@pytest.mark.real_pages
def test_golden_real_pages_have_no_hover_text_leak():
    record = parse_fleet(load(REAL, "fleet_97.html"), FLEET_URL.format(id=97))
    fields = [record.name]
    for ship in record.ships:
        fields.extend([ship.ship_label, ship.commander_text or "", ship.notes])
    for event in record.events:
        fields.append(event.text)
    assert not any("Naval Sailor" in field for field in fields)


@requires_real
@pytest.mark.real_pages
def test_cross_check_with_ship_parser_fleet_id():
    # tests/fixtures/synthetic/ship_full.html lists fleet 139 in its "Fleets" table.
    assert parse_fleet(load(REAL, "fleet_139.html"), FLEET_URL.format(id=139)).fleet_id == 139
