"""The action items (Task A2): plain dataclasses that survive JSON round trips."""

from __future__ import annotations

import dataclasses
import json

from threedecks.items import (
    ActionDivision,
    ActionIndexPage,
    ActionIndexRow,
    ActionRecord,
    ActionSide,
    LinkRef,
    Participant,
    SourceRef,
)
from threedecks.parsing.dates import parse_long_date, parse_td_date


def roundtrip(obj):
    return json.loads(json.dumps(dataclasses.asdict(obj), ensure_ascii=False, sort_keys=True))


def test_action_index_page_round_trips():
    row = ActionIndexRow(
        battle_id=1145,
        name="Battle of Damme",
        date=parse_td_date("30.5.1213"),
        end_date=parse_td_date("31.5.1213"),
        action_type="Fleet action",
        war_id=112,
        war_text="Anglo-French War",
        cells=["30.5.1213 - 31.5.1213", "Battle of Damme", "Fleet action", "War"],
        page=1,
    )
    page = ActionIndexPage(rows=[row], page=1, pages=22, total=1089)
    dumped = roundtrip(page)
    assert dumped["total"] == 1089
    assert dumped["rows"][0]["battle_id"] == 1145
    assert dumped["rows"][0]["date"]["iso"] == "1213-05-30"
    assert dumped["rows"][0]["cells"][2] == "Fleet action"


def test_action_record_round_trips():
    side = ActionSide(
        label="Allied (Spain & Empire Français)",
        nation_ids=[7, 4],
        commander_ids=[16313],
        links=[LinkRef(text="Spain", href="x", id=7, kind="show_nation")],
    )
    division = ActionDivision(
        side_index=0, label="Allied Rear", commander_ids=[1], notes=["held back"], links=[]
    )
    participant = Participant(
        side_index=0,
        division_index=0,
        td_id=2657,
        ship_label="Neptuno (80)",
        ship=LinkRef(
            text="Neptuno (80)", href="y", id=2657, kind="show_ship",
            tooltip=["1795-1805", "Spanish 80 Gun"],
        ),
        commander_ids=[16313],
        commander_text="Commander",
        commanders=[],
        notes="37 Killed, 47 Wounded Captured",
        flags=["Squadron Flagship"],
    )
    start, end = parse_long_date("1805")
    record = ActionRecord(
        battle_id=157,
        name="Battle of Trafalgar",
        header_text="21st October 1805",
        date=start,
        end_date=end,
        war_id=20,
        places=[LinkRef(text="Cape Trafalgar", href="z", id=95, kind="show_shipyard")],
        previous_battle_id=532,
        next_battle_id=158,
        latitude=36.29299,
        longitude=-6.25534,
        sides=[side],
        divisions=[division],
        participants=[participant],
        notes="A long note.",
        sources=[SourceRef(code="B006", title="A source")],
        unknown_rows=["odd"],
        unknown_sections=["Something"],
        url="https://threedecks.org/index.php?display_type=show_battle&id=157",
        fetched_at="2026-10-08T00:00:00Z",
        content_sha256="abc",
        parser_version="1",
    )
    dumped = roundtrip(record)
    assert dumped["participants"][0]["ship"]["tooltip"] == ["1795-1805", "Spanish 80 Gun"]
    assert dumped["participants"][0]["flags"] == ["Squadron Flagship"]
    assert dumped["sides"][0]["nation_ids"] == [7, 4]
    assert dumped["divisions"][0]["notes"] == ["held back"]
    assert dumped["places"][0]["id"] == 95
    assert dumped["sources"][0]["code"] == "B006"
    assert dumped["latitude"] == 36.29299
