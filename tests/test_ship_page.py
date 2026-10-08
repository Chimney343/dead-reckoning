"""Layer 2 and 3: the ship-page parser.

Synthetic fixtures reproduce each markup quirk from Plan 3.2-3.4. Golden tests
run only when ``tests/fixtures/real/`` is present (gitignored) and pin the real
values from Plan section 6.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.ship_page import (
    KNOWN_LABELS,
    LABEL_CATEGORIES,
    is_not_found_page,
    is_ship_page,
    parse_ship,
)

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


def test_fleets_table_without_row_tags(full):
    # Real markup: <tbody><td>...</td></tbody>, no <tr> around the cells.
    assert len(full.fleets) == 1
    fleet = full.fleets[0]
    assert (fleet.fleet_id, fleet.fleet_name) == (139, "Miguel Enriquez's privateer fleet")
    assert (fleet.commander_id, fleet.commander_name) == (49702, "Miguel Enriquez")
    assert (fleet.from_date.iso, fleet.to_date.iso) == ("1704", "1732")
    assert fleet.source_code is None


def test_page_cut_off_before_the_footer_is_incomplete():
    html = (SYNTHETIC / "ship_full.html").read_text(encoding="utf-8")
    assert is_ship_page(Selector(html))
    truncated = html[: html.index("page_footer")]
    assert not is_ship_page(Selector(truncated))


@pytest.mark.parametrize(
    "label",
    ["Home Port", "First Mentioned", "Last known", "First Commissioned", "Extant",
     "Purchased", "Blown Up", "Sunk as Foundation", "Sunk in Action"],
)
def test_labels_seen_in_the_smoke_run_are_known(label):
    assert label in KNOWN_LABELS


@pytest.mark.parametrize(
    "label,category",
    [
        ("National Rate", "attribute"), ("Broken Up to Rebuild", "disposed"),
        ("Sold for Break Up", "disposed"), ("Sunk as Breakwater", "disposed"),
        ("Burnt to avoid capture", "lost"), ("Expended as Fireship", "lost"),
        ("Hired", "acquired"), ("Bought by the Navy", "acquired"), ("Requisitioned", "acquired"),
        ("Returned to Owners", "transferred"), ("Transfered", "transferred"),
        ("Given Away", "transferred"), ("Presented", "transferred"), ("Mutinied", "service"),
        ("Razeed", "service"), ("Hulked", "service"), ("Disarmed", "service"),
        ("Beached", "lost"), ("Condemned", "disposed"), ("Last Mentioned", "attested"),
        ("Deleted from list", "disposed"), ("Abandoned", "lost"), ("Rerated", "service"),
        ("Burnt in Action", "lost"), ("Sunk to avoid capture", "lost"),
    ],
)
def test_labels_seen_overnight_have_a_category(label, category):
    assert LABEL_CATEGORIES[label] == category


@pytest.mark.parametrize(
    "label,category",
    [("Sunk as Blockship", "disposed"), ("Captured and burnt", "captured")],
)
def test_labels_seen_in_the_v3_crawl_have_a_category(label, category):
    assert LABEL_CATEGORIES[label] == category


# --- real-markup quirks found reviewing the v3 crawl -----------------------


@pytest.fixture
def quirks():
    return parse_ship(load(SYNTHETIC, "ship_quirks.html"), URL)


def _base(record, label):
    return next(r for r in record.base_rows if r.label == label)


def test_shipyard_links_in_history_are_not_ship_ids(quirks):
    fitting = quirks.history[0]
    assert fitting.ship_ids == []
    assert fitting.shipyard_ids == [11, 12]


def test_history_text_drops_linked_ship_tooltips(quirks):
    took = quirks.history[1]
    assert took.text == "Took the Privateer Test Privateer (4) off the test coast"
    assert took.ship_ids == [503]


def test_base_row_text_drops_tooltips(quirks):
    assert _base(quirks, "Designed by").text == "Juan Inventado"
    previously = _base(quirks, "Previously")
    assert previously.text == "Spanish Merchant galleon 'Test Galleon' (1740) (40)"


def test_links_inside_tooltips_are_not_row_links(quirks):
    assert [link.kind for link in _base(quirks, "Previously").links] == ["show_ship"]


def test_tooltip_lines_are_kept_on_the_link(quirks):
    designer = _base(quirks, "Designed by").links[0]
    assert designer.tooltip == ["Spanish", "Designer", "Ship Builder", "Service 1750-1760"]
    previous = _base(quirks, "Previously").links[0]
    assert previous.tooltip == ["1740-1741", "Spanish 40 Gun", "Merchant Galleon"]


def test_dimension_header_without_source_is_not_a_data_row(quirks):
    assert len(quirks.dimensions) == 1
    assert [row[0] for row in quirks.dimensions[0].rows] == ["Length of Gundeck", "Breadth"]


def test_officer_with_a_single_date_spans_that_date(quirks):
    single = next(o for o in quirks.officers if o.crewman_id == 504)
    assert (single.from_date.iso, single.to_date.iso) == ("1646", "1646")


def test_officer_with_an_open_range_has_no_end_date(quirks):
    captain = next(o for o in quirks.officers if o.crewman_id == 505)
    assert captain.from_date.iso == "1720-01-27"
    assert captain.to_date is None


def test_lifecycle_dates_carry_their_category(full):
    by_label = {d.label: d.category for d in full.lifecycle}
    assert by_label["Captured"] == "captured"
    assert by_label["Sold"] == "disposed"
