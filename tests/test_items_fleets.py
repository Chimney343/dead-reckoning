"""The fleet items (Task FL2): plain dataclasses that survive JSON round trips."""

from __future__ import annotations

import dataclasses
import json

from threedecks.items import (
    BaseRow,
    FleetEvent,
    FleetIndexRow,
    FleetRecord,
    FleetShip,
    LinkRef,
    SourceRef,
)
from threedecks.parsing.dates import parse_td_date


def roundtrip(obj):
    return json.loads(json.dumps(dataclasses.asdict(obj), ensure_ascii=False, sort_keys=True))


def test_fleet_index_row_round_trips():
    row = FleetIndexRow(
        fleet_id=132,
        name="French Fleet sent to the aid of the Venetians",
        date_from=parse_td_date("2.1501"),
        date_to=parse_td_date("1501"),
        nation_id=None,
        nation_text="Unknown?",
        commander_ids=[4757],
        commanders=[LinkRef(text="Sir James Saumarez", id=4757, kind="show_crewman")],
        cells=["2.1501", "1501", "Unknown?", "French Fleet...", ""],
    )
    dumped = roundtrip(row)
    assert dumped["fleet_id"] == 132
    assert dumped["nation_id"] is None
    assert dumped["date_from"]["iso"] == "1501-02"
    assert dumped["commanders"][0]["id"] == 4757
    assert dumped["cells"][0] == "2.1501"


def test_fleet_ship_round_trips():
    ship = FleetShip(
        td_id=1234,
        ship_label="Orion (74)",
        ship=LinkRef(
            text="Orion (74)",
            href="x",
            id=1234,
            kind="show_ship",
            tooltip=["1787-1814", "British 74 Gun", "3rd Rate Ship of the Line"],
        ),
        joined=parse_td_date("14.8.1798"),
        left=parse_td_date("1798"),
        commander_ids=[4757],
        commander_text="Sir James Saumarez",
        commanders=[LinkRef(text="Sir James Saumarez", id=4757, kind="show_crewman")],
        notes="Fleet disbanded",
        cells=["Orion (74)", "", "14.8.1798", "", "1798", "Sir James Saumarez", "Fleet disbanded"],
    )
    dumped = roundtrip(ship)
    assert dumped["td_id"] == 1234
    assert dumped["ship"]["tooltip"][0] == "1787-1814"
    assert dumped["joined"]["iso"] == "1798-08-14"
    assert dumped["left"]["precision"] == "year"
    assert dumped["commander_ids"] == [4757]
    assert len(dumped["cells"]) == 7


def test_fleet_event_round_trips():
    event = FleetEvent(
        date=parse_td_date("1798/08/14", "Tuesday 14th of August 1798"),
        text="Sailed from Aboukir Bay for Gibraltar and England",
        ship_ids=[1234],
        place_ids=[1740],
        battle_ids=[157],
        links=[LinkRef(text="Aboukir Bay", id=1740, kind="show_shipyard")],
        source_code="B006",
    )
    dumped = roundtrip(event)
    assert dumped["date"]["iso"] == "1798-08-14"
    assert dumped["date"]["tooltip"] == "Tuesday 14th of August 1798"
    assert dumped["place_ids"] == [1740]
    assert dumped["battle_ids"] == [157]
    assert dumped["links"][0]["kind"] == "show_shipyard"


def test_fleet_record_round_trips():
    record = FleetRecord(
        fleet_id=97,
        name="Saumarez's Squadron 1798",
        base_rows=[
            BaseRow(label="Fleet Formed", text="14.8.1798", date=parse_td_date("14.8.1798"),
                    source_code="ref:1239")
        ],
        commander_ids=[4757],
        formed=parse_td_date("14.8.1798"),
        disbanded=parse_td_date("1798"),
        introduction="A privateer fleet.",
        ships=[FleetShip(td_id=1234, ship_label="Orion (74)")],
        events=[FleetEvent(date=parse_td_date("1798"), text="Sailed")],
        sources=[SourceRef(code="B006", title="A source")],
        unknown_labels=["Odd Label"],
        unknown_sections=["Mystery"],
        url="https://threedecks.org/index.php?display_type=show_fleet&id=97",
        fetched_at="2026-10-08T00:00:00Z",
        content_sha256="abc",
        parser_version="1",
    )
    dumped = roundtrip(record)
    assert dumped["fleet_id"] == 97
    assert dumped["formed"]["iso"] == "1798-08-14"
    assert dumped["base_rows"][0]["source_code"] == "ref:1239"
    assert dumped["ships"][0]["ship_label"] == "Orion (74)"
    assert dumped["events"][0]["text"] == "Sailed"
    assert dumped["sources"][0]["code"] == "B006"
    assert dumped["unknown_labels"] == ["Odd Label"]
