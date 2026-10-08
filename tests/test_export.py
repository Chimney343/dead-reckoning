"""The export script writes JSONL and Parquet from state.sqlite (Plan 6)."""

from __future__ import annotations

import json

from threedecks.items import (
    ActionDivision,
    ActionIndexRow,
    ActionRecord,
    ActionSide,
    CaptureRow,
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
