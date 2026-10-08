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


def capture(captured, captors, war=None, text=""):
    return CaptureRow(
        captured_td_id=captured, captured_label="x", date=parse_td_date("1804/12/07"),
        captor_td_ids=captors, captor_text=text, from_nation_id=7, by_nation_id=1, war_id=war,
    )


def test_same_ship_and_date_with_different_captors_are_both_kept(tmp_path):
    # Diligencia (13269), 1804/12/07: listed once for Pique and once for Diana.
    store = StateStore(tmp_path / "state.sqlite")
    store.save_capture(capture(13269, [5823]))
    store.save_capture(capture(13269, [2812]))
    store.save_capture(capture(13269, [], text="Taken by the British"))
    assert store.capture_count() == 3
    store.close()


def test_clear_captures_drops_only_that_query(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.save_capture(capture(1, [2]))
    store.save_capture(capture(1, [2], war=5))
    assert store.clear_captures(7, 1, None) == 1
    assert [row["war_id"] for row in store.iter_captures()] == [5]
    store.close()


def test_a_run_that_never_finished_is_marked_interrupted(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    killed = store.start_run("ships_by_nation")
    store.seed([1], discovered_by="x")
    store.mark_status(1, "done")  # its last sign of life
    store.start_run("captures")  # the next session
    run = store.get_run(killed)
    assert run["close_reason"] == "interrupted"
    assert run["finished_at"] is not None
    store.close()


def test_release_attempts_gives_one_back(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_status(1, "error", increment_attempts=True)
    store.mark_status(1, "error", increment_attempts=True)
    store.release_attempts([1])
    assert (store.status(1), store.attempts(1)) == ("pending", 1)
    store.close()


# --- the generic page frontier (Task S3) --------------------------------------
#
# Action and fleet ids are their own id spaces (battle 157 is not ship 157), so
# they live in ``page_frontier``, keyed by (kind, page_key), beside the ship
# ``frontier``.

OLD_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    td_id INTEGER PRIMARY KEY,
    discovered_by TEXT,
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    last_error TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ships (
    td_id INTEGER PRIMARY KEY,
    record_json TEXT NOT NULL,
    parser_version TEXT,
    content_sha256 TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS captures (
    key TEXT PRIMARY KEY,
    row_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    spider TEXT,
    started_at TEXT,
    finished_at TEXT,
    close_reason TEXT,
    pages_fetched INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS frontier_status ON frontier (status, td_id);
"""


def test_seed_pages_is_idempotent_and_returns_only_new_keys(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    assert store.seed_pages("action", ["10", "2", "2"], discovered_by="history") == ["10", "2"]
    assert store.seed_pages("action", ["2", "3"], discovered_by="index") == ["3"]
    store.close()


def test_pending_pages_are_in_numeric_order(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action", ["10", "9", "2"], discovered_by="x")
    assert list(store.pending_pages("action")) == ["2", "9", "10"]
    store.close()


def test_page_namespaces_are_separate_from_ships(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed([157], discovered_by="test")
    store.save_ship(make_ship(157))
    store.seed_pages("action", ["157"], discovered_by="test")
    assert store.status(157) == "done"
    assert store.page_status("action", "157") == "pending"
    store.close()


def test_page_attempts_count_up_and_cap(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action", ["5"], discovered_by="x")
    for _ in range(3):
        store.mark_page_status("action", "5", "error", error="boom", increment_attempts=True)
    assert store.page_attempts("action", "5") == 3
    assert list(store.pending_pages("action", max_attempts=3)) == []
    store.close()


def test_release_page_attempts_gives_one_back(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_page_status("action", "1", "error", increment_attempts=True)
    store.mark_page_status("action", "1", "error", increment_attempts=True)
    store.release_page_attempts("action", ["1"])
    assert (store.page_status("action", "1"), store.page_attempts("action", "1")) == ("pending", 1)
    store.close()


def test_page_counts_by_status(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    store.seed_pages("action_index", ["1", "2", "3"], discovered_by="x")
    store.mark_page_status("action_index", "1", "done")
    store.mark_page_status("action_index", "2", "not_found")
    counts = store.page_counts_by_status("action_index")
    assert counts["pending"] == 1
    assert counts["done"] == 1
    assert counts["not_found"] == 1
    store.close()


def test_reopen_keeps_the_page_frontier(tmp_path):
    path = tmp_path / "state.sqlite"
    store = StateStore(path)
    store.seed_pages("action", ["9"], discovered_by="x")
    store.mark_page_status("action", "9", "done")
    store.close()

    reopened = StateStore(path)
    assert reopened.page_status("action", "9") == "done"
    reopened.close()


def test_close_open_runs_uses_a_page_frontier_update_time(tmp_path):
    store = StateStore(tmp_path / "state.sqlite")
    killed = store.start_run("actions")
    with store._conn:  # noqa: SLF001
        store._conn.execute(  # noqa: SLF001
            "UPDATE runs SET started_at = ? WHERE run_id = ?",
            ("2020-01-01T00:00:00Z", killed),
        )
        store._conn.execute(  # noqa: SLF001
            "INSERT INTO page_frontier (kind, page_key, status, updated_at) "
            "VALUES ('action', '1', 'done', '2020-01-01T00:05:00Z')"
        )
    store.start_run("captures")  # the next session closes the interrupted one
    assert store.get_run(killed)["finished_at"] == "2020-01-01T00:05:00Z"
    store.close()


def test_opening_an_old_schema_adds_the_page_frontier(tmp_path):
    import sqlite3

    path = tmp_path / "state.sqlite"
    conn = sqlite3.connect(str(path))
    conn.executescript(OLD_SCHEMA)
    conn.execute(
        "INSERT INTO ships (td_id, record_json) VALUES (2682, '{\"td_id\": 2682}')"
    )
    conn.execute("INSERT INTO frontier (td_id, status) VALUES (2682, 'done')")
    conn.commit()
    conn.close()

    store = StateStore(path)
    assert store.get_ship(2682)["td_id"] == 2682
    assert store.status(2682) == "done"
    store.seed_pages("action", ["1"], discovered_by="x")
    assert store.page_status("action", "1") == "pending"
    store.close()
