"""Layer 2/3: the action index and action page parsers (Three Decks actions plan 3)."""

from __future__ import annotations

from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.actions import (
    is_action_index_page,
    is_action_not_found,
    is_action_page,
    parse_action,
    parse_action_index,
)
from threedecks.parsing.ship_page import parse_ship

SYNTHETIC = Path(__file__).parent / "fixtures" / "synthetic"
REAL = Path(__file__).parent / "fixtures" / "real"
URL = "https://threedecks.org/index.php?display_type=show_battle&id={id}"

requires_real = pytest.mark.skipif(
    not REAL.exists(), reason="tests/fixtures/real/ is absent (run scripts/fetch_fixtures.py)"
)


def load(path, name):
    return Selector((path / name).read_text(encoding="utf-8"))


@pytest.fixture
def full():
    return parse_action(load(SYNTHETIC, "action_full.html"), URL.format(id=555))


# --- completeness signatures ------------------------------------------------


def test_is_action_page():
    assert is_action_page(load(SYNTHETIC, "action_full.html"))
    assert is_action_page(load(SYNTHETIC, "action_minimal.html"))
    assert not is_action_page(load(SYNTHETIC, "action_truncated.html"))
    assert not is_action_page(load(SYNTHETIC, "action_notfound.html"))


def test_is_action_not_found():
    assert is_action_not_found(load(SYNTHETIC, "action_notfound.html"))
    assert not is_action_not_found(load(SYNTHETIC, "action_minimal.html"))


def test_is_action_index_page():
    assert is_action_index_page(load(SYNTHETIC, "action_index.html"))
    assert not is_action_index_page(load(SYNTHETIC, "action_minimal.html"))


# --- the index --------------------------------------------------------------


def test_parse_action_index_synthetic():
    page = parse_action_index(load(SYNTHETIC, "action_index.html"))
    assert (page.total, page.page, page.pages) == (3, 1, 2)
    assert len(page.rows) == 3
    first = page.rows[0]
    assert first.battle_id == 1145
    assert first.name == "Battle of Damme"
    assert (first.date.iso, first.end_date.iso) == ("1213-05-30", "1213-05-31")
    assert first.action_type == "Fleet action"
    assert first.war_id == 112
    assert first.cells[2] == "Fleet action"

    second = page.rows[1]
    assert second.battle_id == 938 and second.end_date is None and second.war_id is None
    orphan = page.rows[2]
    assert orphan.battle_id is None and orphan.name == "Orphan Action"


# --- a full action page -----------------------------------------------------


def test_full_header(full):
    assert full.name == "Battle of Example"
    assert (full.date.iso, full.date.gregorian_iso) == ("1563-05-22", "1563-05-31")
    assert (full.end_date.iso, full.end_date.gregorian_iso) == ("1563-07-31", "1563-08-09")
    assert full.war_id == 77
    assert [link.id for link in full.places] == [95, 1222]
    assert (full.previous_battle_id, full.next_battle_id) == (100, 200)


def test_full_coordinates(full):
    assert (full.latitude, full.longitude) == (49.49, 0.1)


def test_full_sides_and_divisions(full):
    assert [side.nation_ids for side in full.sides] == [[7, 4], [1]]
    assert full.sides[0].commander_ids == [500]
    assert [d.label for d in full.divisions] == [
        "Allied Rear, Rear Admiral",
        "Allied Van",
        "British Vessels",
    ]
    assert [d.side_index for d in full.divisions] == [0, 0, 1]
    assert full.divisions[0].commander_ids == [501]
    assert full.divisions[0].notes == ["Rear division held back."]


def test_full_participants(full):
    assert len(full.participants) == 6
    alpha = full.participants[0]
    assert alpha.td_id == 1001
    assert alpha.ship_label == "Alpha (80)"
    assert alpha.ship.tooltip == ["1795-1805", "Spanish 80 Gun", "3rd Rate Ship of the Line"]
    assert alpha.commander_ids == [601]
    assert alpha.commander_text == "Captain A"
    assert alpha.notes == "Squadron Flagship 37 Killed, 47 Wounded Captured"
    assert alpha.flags == ["Squadron Flagship"]
    assert (alpha.side_index, alpha.division_index) == (0, 0)

    assert full.participants[1].commander_text is None  # nbsp commander
    unlinked = full.participants[2]
    assert unlinked.td_id is None and unlinked.ship is None
    assert unlinked.ship_label == "Unlinked Ship (50)"
    # The cell also holds a show_shipyard link; it must not become the td_id.
    gamma = full.participants[3]
    assert gamma.td_id == 1004
    assert gamma.ship_label == "Gamma (64)"


def test_full_sections(full):
    assert full.notes == "Some note text."
    assert len(full.sources) == 1
    assert full.sources[0].code == "B006"
    assert full.unknown_rows == ["odd"]
    assert full.unknown_sections == ["Mystery Section"]


def test_no_visible_field_carries_hover_text(full):
    fields = [full.name]
    for side in full.sides:
        fields.append(side.label)
    for division in full.divisions:
        fields.append(division.label)
    for participant in full.participants:
        fields.extend([participant.ship_label, participant.commander_text or "", participant.notes])
    assert not any("Naval Sailor" in field for field in fields)


def test_minimal_action_page():
    record = parse_action(load(SYNTHETIC, "action_minimal.html"), URL.format(id=42))
    assert record.name == "Minimal Action"
    assert record.date.iso == "1700-01-01"
    assert record.war_id is None and record.places == []
    assert (record.latitude, record.longitude) == (None, None)
    assert len(record.sides) == 1 and record.sides[0].nation_ids == [1]
    assert record.divisions == []
    assert len(record.participants) == 1
    assert record.participants[0].td_id == 42
    assert record.notes is None
    assert record.unknown_rows == [] and record.unknown_sections == []


# --- golden tests on real pages (skipped without fixtures) -----------------


@requires_real
@pytest.mark.real_pages
def test_golden_157_trafalgar():
    record = parse_action(load(REAL, "action_157.html"), URL.format(id=157))
    assert record.name == "Battle of Trafalgar"
    assert record.date.iso == "1805-10-21"
    assert record.war_id == 20
    assert (record.previous_battle_id, record.next_battle_id) == (532, 158)
    assert (record.latitude, record.longitude) == (36.29299, -6.25534)
    assert [side.nation_ids for side in record.sides] == [[7, 4], [1]]
    assert len(record.divisions) == 8
    assert len(record.participants) == 73
    assert all(p.td_id is not None for p in record.participants)
    assert 2682 in {p.td_id for p in record.participants}

    first = record.participants[0]
    assert first.td_id == 2657
    assert first.ship_label == "Neptuno (80)"
    assert first.ship.tooltip == ["1795-1805", "Spanish 80 Gun", "3rd Rate Ship of the Line"]
    assert first.commander_ids == [16313]
    assert first.commanders[0].tooltip[0] == "Spanish"
    assert first.notes == "37 Killed, 47 Wounded Captured"
    assert any("Squadron Flagship" in p.flags for p in record.participants)
    assert len(record.sources) == 2
    assert record.notes is not None


@requires_real
@pytest.mark.real_pages
def test_golden_149_cape_st_vincent():
    record = parse_action(load(REAL, "action_149.html"), URL.format(id=149))
    assert len(record.participants) == 55
    ids = {p.td_id for p in record.participants}
    assert 2682 in ids and 112 not in ids
    assert [side.nation_ids for side in record.sides] == [[7], [1]]
    assert len(record.divisions) == 6
    assert record.war_id == 19
    assert (record.previous_battle_id, record.next_battle_id) == (684, 217)
    assert (record.latitude, record.longitude) == (None, None)
    assert record.sources == []


@requires_real
@pytest.mark.real_pages
def test_golden_532_single_ship():
    record = parse_action(load(REAL, "action_532.html"), URL.format(id=532))
    assert len(record.participants) == 2
    assert [side.nation_ids for side in record.sides] == [[1], [4]]
    assert record.divisions == []
    assert record.war_id == 20
    assert (record.previous_battle_id, record.next_battle_id) == (199, 157)


@requires_real
@pytest.mark.real_pages
def test_golden_988_siege_of_le_havre():
    record = parse_action(load(REAL, "action_988.html"), URL.format(id=988))
    assert (record.date.iso, record.date.gregorian_iso) == ("1563-05-22", "1563-05-31")
    assert (record.end_date.iso, record.end_date.gregorian_iso) == ("1563-07-31", "1563-08-09")
    assert [link.id for link in record.places] == [95, 1222]
    assert record.war_id is None
    assert [side.nation_ids for side in record.sides] == [[1]]
    assert len(record.divisions) == 1
    assert record.divisions[0].label == "English Vessels"
    assert len(record.divisions[0].notes) == 1
    assert len(record.participants) == 5
    assert (record.latitude, record.longitude) == (49.49, 0.1)


@requires_real
@pytest.mark.real_pages
@pytest.mark.parametrize("battle_id", [157, 149, 532, 988])
def test_golden_actions_are_clean(battle_id):
    record = parse_action(load(REAL, f"action_{battle_id}.html"), URL.format(id=battle_id))
    assert is_action_page(load(REAL, f"action_{battle_id}.html"))
    assert record.unknown_rows == []
    assert record.unknown_sections == []
    fields = [record.name]
    for side in record.sides:
        fields.append(side.label)
    for division in record.divisions:
        fields.append(division.label)
    for participant in record.participants:
        fields.extend([participant.ship_label, participant.commander_text or "", participant.notes])
    assert not any("Naval Sailor" in field for field in fields)


@requires_real
@pytest.mark.real_pages
def test_golden_not_found_probe():
    sel = load(REAL, "action_notfound_probe.html")
    assert is_action_not_found(sel)
    assert not is_action_page(sel)


@requires_real
@pytest.mark.real_pages
def test_golden_action_index():
    page = parse_action_index(load(REAL, "action_index.html"))
    assert len(page.rows) == 50
    assert page.total == 1089
    assert (page.page, page.pages) == (1, 22)
    first = page.rows[0]
    assert first.battle_id == 1145
    assert first.name == "Battle of Damme"
    assert (first.date.iso, first.end_date.iso) == ("1213-05-30", "1213-05-31")
    assert first.action_type == "Fleet action"
    assert first.war_id == 112
    assert sum(1 for row in page.rows if row.end_date is not None) == 15
    assert sum(1 for row in page.rows if row.war_id is None) == 8


@requires_real
@pytest.mark.real_pages
def test_golden_action_index_page_2():
    page = parse_action_index(load(REAL, "action_index_p2.html"))
    assert (page.page, page.pages) == (2, 22)
    first = page.rows[0]
    assert first.battle_id == 938
    assert first.name == "Battle of Sluis"
    assert first.date.iso == "1603-05-26"


@requires_real
@pytest.mark.real_pages
def test_ship_history_battles_are_participants():
    ship = parse_ship(load(REAL, "ship_2682.html"), "https://threedecks.org/index.php?display_type=show_ship&id=2682")
    linked = {b for event in ship.history for b in event.battle_ids}
    for battle_id in (149, 157):
        if battle_id in linked:
            record = parse_action(load(REAL, f"action_{battle_id}.html"), URL.format(id=battle_id))
            assert 2682 in {p.td_id for p in record.participants}
