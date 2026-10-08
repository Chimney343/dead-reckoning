"""Layer 5 for actions: resume, block, cool-off and the crawl lock (Task A7)."""

from __future__ import annotations

import pickle
import sqlite3
import subprocess
import sys
import time
import zlib
from pathlib import Path

from resume_harness import (
    ACTION_PAGE,
    REPO_ROOT,
    FakeSite,
    add_action_routes,
    crawl_env,
    run_crawl,
    start_crawl,
)
from threedecks.items import HistoryEvent, ShipRecord
from threedecks.lock import CrawlLock
from threedecks.state import StateStore

ACTIONS = list(range(1, 121))  # 3 index pages of 50


def seed_ship_battles(data_dir: Path, battle_ids: list[int]) -> None:
    store = StateStore(data_dir / "state.sqlite")
    store.save_ship(
        ShipRecord(td_id=1, name="Seed", history=[HistoryEvent(text="x", battle_ids=battle_ids)])
    )
    store.close()


def last_reason(data_dir: Path) -> str | None:
    store = StateStore(data_dir / "state.sqlite")
    try:
        row = store._conn.execute(  # noqa: SLF001
            "SELECT close_reason FROM runs ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        return row["close_reason"] if row else None
    finally:
        store.close()


def test_graceful_stop_then_resume(tmp_path):
    site = FakeSite([])
    add_action_routes(site, ACTIONS)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    seed_ship_battles(data, [900001, 900002])
    try:
        rc, out = run_crawl(
            data, site.base_url, ["-s", "CLOSESPIDER_ITEMCOUNT=40"], spider="actions"
        )
        assert rc == 0, out[-3000:]
        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            assert store.action_count() == len(ACTIONS)
            assert all(store.page_status("action", str(i)) == "done" for i in ACTIONS)
            assert store.page_status("action", "900001") == "not_found"
            assert store.page_status("action", "900002") == "not_found"
            assert len({row["battle_id"] for row in store.iter_actions()}) == len(ACTIONS)
        finally:
            store.close()
        assert all(site.count_page("show_battle", str(i)) == 1 for i in ACTIONS)
        assert [site.count_page("select_action", str(p)) for p in (1, 2, 3)] == [1, 1, 1]
    finally:
        site.stop()


def test_hard_kill_then_resume(tmp_path):
    site = FakeSite([])
    add_action_routes(site, ACTIONS)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        proc = start_crawl(data, site.base_url, spider="actions")
        deadline = time.time() + 60
        while proc.poll() is None and time.time() < deadline:
            if sum(site.count_page("show_battle", str(i)) for i in ACTIONS) >= 40:
                break
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.page_status("action", str(i)) == "done" for i in ACTIONS)
        finally:
            store.close()
        counts = [site.count_page("show_battle", str(i)) for i in ACTIONS]
        assert min(counts) >= 1
        assert max(counts) <= 2  # at most the one in-flight page is refetched
    finally:
        site.stop()


def corrupt_cached_action(data_dir: Path, battle_id: int) -> None:
    footerless = ACTION_PAGE.format(action_id=battle_id).split(
        "<span id=\"copywrite_message\""
    )[0]
    conn = sqlite3.connect(str(data_dir / "httpcache.sqlite"))
    try:
        for fingerprint, blob in conn.execute("SELECT fingerprint, data FROM responses"):
            payload = pickle.loads(zlib.decompress(blob))
            url = payload.get("url") or ""
            if "display_type=show_battle" in url and f"id={battle_id}" in url:
                payload["body"] = footerless.encode()
                conn.execute(
                    "UPDATE responses SET data = ? WHERE fingerprint = ?",
                    (zlib.compress(pickle.dumps(payload, protocol=4)), fingerprint),
                )
        conn.commit()
    finally:
        conn.close()


def test_truncated_cache_entry_is_refetched(tmp_path):
    ids = list(range(1, 6))
    site = FakeSite([])
    add_action_routes(site, ids)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]

        corrupt_cached_action(data, 3)
        store = StateStore(data / "state.sqlite")
        with store._conn:  # noqa: SLF001 - simulate a record lost to a crash
            store._conn.execute("DELETE FROM actions WHERE battle_id = 3")
            store._conn.execute(
                "UPDATE page_frontier SET status = 'pending' "
                "WHERE kind = 'action' AND page_key = '3'"
            )
        store.close()

        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert store.page_status("action", "3") == "done"
            assert store.get_action(3)["battle_id"] == 3
            assert store.action_count() == len(ids)
        finally:
            store.close()
        assert site.count_page("show_battle", "3") >= 2
    finally:
        site.stop()


def test_interrupted_index_sweep_resumes(tmp_path):
    site = FakeSite([])
    add_action_routes(site, ACTIONS)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    site.action_block_page, site.action_block_active = 2, True
    try:
        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert store.page_status("action_index", "1") == "done"
        finally:
            store.close()
        assert last_reason(data) == "blocked"
        assert site.count_page("select_action", "1") == 1

        site.action_block_active = False
        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert store.page_status("action_index", "1") == "done"
            assert store.page_status("action_index", "2") == "done"
            assert store.page_status("action_index", "3") == "done"
        finally:
            store.close()
        assert site.count_page("select_action", "1") == 1  # never fetched again
        assert site.count_page("select_action", "2") >= 1
        assert site.count_page("select_action", "3") >= 1
    finally:
        site.stop()


def test_action_rate_limit_is_waited_out(tmp_path):
    ids = list(range(1, 21))
    site = FakeSite([])
    add_action_routes(site, ids)
    site.action_block_id, site.action_block_active, site.action_block_limit = 10, True, 1
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        cooloff = ["-s", "THREEDECKS_MAX_COOLOFFS=2", "-s", "THREEDECKS_COOLOFF_SECS=1"]
        rc, out = run_crawl(data, site.base_url, cooloff, spider="actions")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert last_reason(data) == "finished"
            assert all(store.page_status("action", str(i)) == "done" for i in ids)
        finally:
            store.close()
        assert site.count_page("show_battle", "10") == 2  # retried once, unchanged
    finally:
        site.stop()


def test_crawl_lock_blocks_the_actions_driver(tmp_path):
    site = FakeSite([])
    add_action_routes(site, list(range(1, 6)))
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    command = [
        sys.executable, "scripts/crawl.py", "--tiers", "actions", "--allow-sleep",
        "--pause-seconds", "0",
        "-s", "DOWNLOAD_DELAY=0",
        "-s", "DOWNLOAD_DELAY_JITTER=0",
        "-s", "AUTOTHROTTLE_ENABLED=False",
        "-s", "THREEDECKS_MAX_COOLOFFS=0",
    ]
    env = crawl_env(data, site.base_url)
    try:
        with CrawlLock(data / "crawl.lock"):
            locked = subprocess.run(
                command, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120
            )
            assert locked.returncode == 2, locked.stdout + locked.stderr
            assert site.count_page("show_battle", "1") == 0
            assert site.count_page("select_action", "1") == 0

        completed = subprocess.run(
            command, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.page_status("action", str(i)) == "done" for i in range(1, 6))
        finally:
            store.close()
    finally:
        site.stop()


def test_ship_and_action_namespaces_coexist(tmp_path):
    site = FakeSite([157])
    add_action_routes(site, [157])
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, spider="ships_all")
        assert rc == 0, out[-3000:]
        rc, out = run_crawl(data, site.base_url, spider="actions")
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            assert store.status(157) == "done"
            assert store.get_ship(157)["td_id"] == 157
            assert store.page_status("action", "157") == "done"
            assert store.get_action(157)["battle_id"] == 157
        finally:
            store.close()
    finally:
        site.stop()
