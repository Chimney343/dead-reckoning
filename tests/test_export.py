"""The export script writes JSONL and Parquet from state.sqlite (Plan 6)."""

from __future__ import annotations

import json

from threedecks.items import CaptureRow, ShipRecord
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
