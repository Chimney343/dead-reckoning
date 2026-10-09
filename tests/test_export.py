"""The export script writes JSONL and Parquet from state.sqlite (Plan 6)."""

from __future__ import annotations

import json

from threedecks.items import (
    ActionDivision,
    ActionIndexRow,
    ActionRecord,
    ActionSide,
    CaptureRow,
    FleetEvent,
    FleetIndexRow,
    FleetRecord,
    FleetShip,
    LinkRef,
    Participant,
    ShipRecord,
)
from threedecks.parsing.dates import parse_td_date
from threedecks.state import StateStore

from scripts.export import main


def test_export_writes_jsonl_and_parquet(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_ship(ShipRecord(td_id=1, name="One", url="https://x/1"))
    store.save_ship(ShipRecord(td_id=2, name="Two", url="https://x/2"))
    store.save_capture(
        CaptureRow(captured_td_id=2, captured_label="Two", date=parse_td_date("1704/04/16"))
    )
    store.close()

    out = tmp_path / "exports"
    assert main(["--data-dir", str(tmp_path), "--out", str(out)]) == 0

    ship_lines = (out / "ships.jsonl").read_text(encoding="utf-8").splitlines()
    capture_lines = (out / "captures.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(ship_lines) == 2
    assert len(capture_lines) == 1
    assert json.loads(ship_lines[0])["td_id"] == 1
    assert (out / "ships.parquet").exists()
    assert (out / "captures.parquet").exists()


def test_export_writes_action_files(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_action_index_page(
        "1", [ActionIndexRow(battle_id=1, name="One", action_type="Fleet action")]
    )
    record = ActionRecord(
        battle_id=1,
        name="One",
        date=parse_td_date("1805/10/21"),
        latitude=36.29,
        longitude=-6.25,
        places=[LinkRef(text="Cape", id=9, kind="show_shipyard")],
        sides=[ActionSide(label="Allied", nation_ids=[7, 4])],
        divisions=[ActionDivision(label="Rear")],
        participants=[
            Participant(
                side_index=0,
                division_index=0,
                td_id=5,
                ship_label="Neptuno (80)",
                notes="n",
                flags=["Squadron Flagship"],
            )
        ],
        url="https://x/1",
    )
    store.save_action(record)
    store.close()

    out = tmp_path / "exports"
    assert main(["--data-dir", str(tmp_path), "--out", str(out)]) == 0

    action_lines = (out / "actions.jsonl").read_text(encoding="utf-8").splitlines()
    index_lines = (out / "action_index.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(action_lines) == 1
    assert json.loads(action_lines[0])["battle_id"] == 1
    assert len(index_lines) == 1

    assert (out / "actions.parquet").exists()
    assert (out / "action_participants.parquet").exists()
    import pandas as pd

    actions = pd.read_parquet(out / "actions.parquet")
    assert list(actions["battle_id"]) == [1]
    assert actions.iloc[0]["action_type"] == "Fleet action"
    assert actions.iloc[0]["place_ids"] == "9"
    participants = pd.read_parquet(out / "action_participants.parquet")
    assert list(participants["battle_id"]) == [1]
    assert participants.iloc[0]["side_label"] == "Allied"
    assert participants.iloc[0]["division_label"] == "Rear"
    assert participants.iloc[0]["ship_tooltip"] == ""


def test_export_writes_fleet_files(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_fleet_index(
        [FleetIndexRow(fleet_id=1, name="One", nation_id=7)]
    )
    store.save_fleet(
        FleetRecord(
            fleet_id=1,
            name="One",
            ships=[
                FleetShip(
                    td_id=5,
                    ship_label="Ship 5",
                    joined=parse_td_date("1798/08/14"),
                    left=parse_td_date("1800"),
                )
            ],
            events=[
                FleetEvent(date=parse_td_date("1798"), text="evt", place_ids=[9], ship_ids=[5])
            ],
            url="u1",
        )
    )
    store.save_fleet(FleetRecord(fleet_id=2, name="Two", url="u2"))
    store.close()

    out = tmp_path / "exports"
    assert main(["--data-dir", str(tmp_path), "--out", str(out)]) == 0

    fleet_lines = (out / "fleets.jsonl").read_text(encoding="utf-8").splitlines()
    index_lines = (out / "fleet_index.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(fleet_lines) == 2
    assert len(index_lines) == 1
    assert (out / "fleets.parquet").exists()
    assert (out / "fleet_ships.parquet").exists()
    assert (out / "fleet_events.parquet").exists()

    import pandas as pd

    fleets = pd.read_parquet(out / "fleets.parquet").set_index("fleet_id")
    assert sorted(fleets.index) == [1, 2]
    assert fleets.loc[1]["nation_id"] == 7
    assert fleets.loc[1]["ship_count"] == 1
    assert fleets.loc[1]["event_count"] == 1
    assert fleets.loc[1]["formed_iso"] is None

    ships = pd.read_parquet(out / "fleet_ships.parquet")
    assert list(ships["fleet_id"]) == [1]
    assert ships.iloc[0]["td_id"] == 5
    assert ships.iloc[0]["joined_iso"] == "1798-08-14"

    events = pd.read_parquet(out / "fleet_events.parquet")
    assert list(events["fleet_id"]) == [1]
    assert events.iloc[0]["place_ids"] == "9"
    assert events.iloc[0]["ship_ids"] == "5"
    assert not ships["fleet_id"].isna().any()
    assert not events["fleet_id"].isna().any()
