"""Layer 5: the SQLite StateStore (Plan 4.3).

Progress lives on disk: the frontier survives a crash, a page is only ``done``
together with its record, and reopening the file keeps everything.
"""

from __future__ import annotations

import json

from threedecks.items import CaptureRow, ShipRecord
from threedecks.parsing.dates import parse_td_date
from threedecks.state import StateStore


def make_ship(td_id: int = 2682) -> ShipRecord:
    return ShipRecord(td_id=td_id, name=f"Ship {td_id}", url=f"https://x/{td_id}")


def test_seeding_is_idempotent(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([1, 2, 2, 3], discovered_by="sitemap")
    store.seed([1, 2, 3, 4], discovered_by="sitemap")
    assert list(store.pending_ids()) == [1, 2, 3, 4]
    store.close()


def test_pending_is_ascending_and_excludes_done(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([30, 10, 20], discovered_by="test")
    store.mark_status(10, "not_found")
    assert list(store.pending_ids()) == [20, 30]
    store.close()


def test_done_and_record_are_written_together(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([2682], discovered_by="test")
    store.save_ship(make_ship(2682))
    assert store.status(2682) == "done"
    assert store.get_ship(2682)["td_id"] == 2682
    store.close()


def test_attempts_increase_and_cap(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([7], discovered_by="test")
    for _ in range(3):
        store.mark_status(7, "error", error="boom", increment_attempts=True)
    assert store.attempts(7) == 3
    assert list(store.pending_ids(max_attempts=3)) == []
    store.close()


def test_reopen_keeps_everything(tmp_path):
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    store.seed([5], discovered_by="test")
    store.save_ship(make_ship(5))
    store.close()

    reopened = StateStore(path)
    assert reopened.status(5) == "done"
    assert reopened.get_ship(5)["name"] == "Ship 5"
    reopened.close()


def test_captures_are_keyed_and_upserted(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    row = CaptureRow(
        captured_td_id=2,
        captured_label="Captured (2)",
        date=parse_td_date("1704/04/16"),
        captor_td_ids=[3],
        from_nation_id=7,
        by_nation_id=1,
        war_id=None,
    )
    store.save_capture(row)
    store.save_capture(row)
    assert store.capture_count() == 1
    store.close()


def test_runs_are_recorded(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    run_id = store.start_run("ships_all")
    store.finish_run(run_id, close_reason="finished", pages_fetched=12)
    run = store.get_run(run_id)
    assert run["spider"] == "ships_all"
    assert run["pages_fetched"] == 12
    assert run["close_reason"] == "finished"
    store.close()


def test_counts_by_status(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([1, 2, 3, 4], discovered_by="test")
    store.mark_status(1, "not_found")
    store.mark_status(2, "error")
    counts = store.counts_by_status()
    assert counts["pending"] == 2
    assert counts["not_found"] == 1
    assert counts["error"] == 1
    store.close()


def test_get_ship_returns_parsed_json(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([9], discovered_by="test")
    store.save_ship(make_ship(9))
    raw = store.get_ship(9)
    assert json.loads(json.dumps(raw))["td_id"] == 9
    store.close()
