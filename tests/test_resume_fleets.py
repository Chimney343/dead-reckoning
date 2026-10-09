"""Layer 5 for fleets: resume, block, cool-off and the crawl lock (Task FL7)."""

from __future__ import annotations

import json
import pickle
import sqlite3
import subprocess
import sys
import time
import zlib
from pathlib import Path

from resume_harness import (
    FLEET_PAGE,
    REPO_ROOT,
    FakeSite,
    add_fleet_routes,
    crawl_env,
    run_crawl,
    start_crawl,
)
from threedecks.items import FleetRow, ShipRecord
from threedecks.lock import CrawlLock
from threedecks.state import StateStore

from scripts.export import main as export_main

FLEETS = list(range(1, 61))  # 60 fleets


def seed_ship_fleets(data_dir: Path, fleet_ids: list[int]) -> None:
    store = StateStore(data_dir / "state.sqlite")
    store.save_ship(
        ShipRecord(
            td_id=1,
            name="Seed",
            fleets=[FleetRow(fleet_id=i) for i in fleet_ids],
        )
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
    add_fleet_routes(site, FLEETS)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    seed_ship_fleets(data, [900001])
    try:
        rc, out = run_crawl(
            data, site.base_url, ["-s", "CLOSESPIDER_ITEMCOUNT=20"], spider="fleets"
        )
        assert rc == 0, out[-3000:]
        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            assert store.fleet_count() == len(FLEETS)
            assert all(store.page_status("fleet", str(i)) == "done" for i in FLEETS)
            assert store.page_status("fleet", "900001") == "not_found"
        finally:
            store.close()
        assert site.count_page("show_fleetlist", "1") == 1
        assert all(site.count_page("show_fleet", str(i)) == 1 for i in FLEETS)

        assert export_main(["--data-dir", str(data), "--out", str(data / "exports")]) == 0
        lines = (data / "exports" / "fleets.jsonl").read_text(encoding="utf-8").splitlines()
        assert len({json.loads(line)["fleet_id"] for line in lines}) == len(FLEETS)
    finally:
        site.stop()


def test_hard_kill_then_resume(tmp_path):
    site = FakeSite([])
    add_fleet_routes(site, FLEETS)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        proc = start_crawl(data, site.base_url, spider="fleets")
        deadline = time.time() + 60
        while proc.poll() is None and time.time() < deadline:
            if sum(site.count_page("show_fleet", str(i)) for i in FLEETS) >= 20:
                break
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.page_status("fleet", str(i)) == "done" for i in FLEETS)
        finally:
            store.close()
        counts = [site.count_page("show_fleet", str(i)) for i in FLEETS]
        assert min(counts) >= 1
        assert max(counts) <= 2  # at most the one in-flight page is refetched
    finally:
        site.stop()


def corrupt_cached_fleet(data_dir: Path, fleet_id: int) -> None:
    footerless = FLEET_PAGE.format(fleet_id=fleet_id).split(
        '<span id="copywrite_message"'
    )[0]
    conn = sqlite3.connect(str(data_dir / "httpcache.sqlite"))
    try:
        for fingerprint, blob in conn.execute("SELECT fingerprint, data FROM responses"):
            payload = pickle.loads(zlib.decompress(blob))
            url = payload.get("url") or ""
            if "display_type=show_fleet" in url and f"id={fleet_id}" in url:
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
    add_fleet_routes(site, ids)
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]

        corrupt_cached_fleet(data, 3)
        store = StateStore(data / "state.sqlite")
        with store._conn:  # noqa: SLF001 - simulate a record lost to a crash
            store._conn.execute("DELETE FROM fleets WHERE fleet_id = 3")
            store._conn.execute(
                "UPDATE page_frontier SET status = 'pending' "
                "WHERE kind = 'fleet' AND page_key = '3'"
            )
        store.close()

        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert store.page_status("fleet", "3") == "done"
            assert store.get_fleet(3)["fleet_id"] == 3
            assert store.fleet_count() == len(ids)
        finally:
            store.close()
        assert site.count_page("show_fleet", "3") >= 2
    finally:
        site.stop()


def test_blocked_then_resume_does_not_refetch_the_index(tmp_path):
    site = FakeSite([])
    add_fleet_routes(site, FLEETS)
    site.fleet_block_id, site.fleet_block_active = 30, True
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert store.page_status("fleet_index", "1") == "done"
        finally:
            store.close()
        assert last_reason(data) == "blocked"
        assert site.count_page("show_fleetlist", "1") == 1

        site.fleet_block_active = False
        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.page_status("fleet", str(i)) == "done" for i in FLEETS)
        finally:
            store.close()
        assert site.count_page("show_fleetlist", "1") == 1  # never fetched again
    finally:
        site.stop()


def test_fleet_rate_limit_is_waited_out(tmp_path):
    ids = list(range(1, 21))
    site = FakeSite([])
    add_fleet_routes(site, ids)
    site.fleet_block_id, site.fleet_block_active, site.fleet_block_limit = 10, True, 1
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        cooloff = ["-s", "THREEDECKS_MAX_COOLOFFS=2", "-s", "THREEDECKS_COOLOFF_SECS=1"]
        rc, out = run_crawl(data, site.base_url, cooloff, spider="fleets")
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert last_reason(data) == "finished"
            assert all(store.page_status("fleet", str(i)) == "done" for i in ids)
        finally:
            store.close()
        assert site.count_page("show_fleet", "10") == 2  # retried once, unchanged
    finally:
        site.stop()


def test_crawl_lock_blocks_the_fleets_driver(tmp_path):
    site = FakeSite([])
    add_fleet_routes(site, list(range(1, 6)))
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    command = [
        sys.executable, "scripts/crawl.py", "--tiers", "fleets", "--allow-sleep",
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
            assert site.count_page("show_fleetlist", "1") == 0
            assert site.count_page("show_fleet", "1") == 0

        completed = subprocess.run(
            command, cwd=str(REPO_ROOT), env=env, capture_output=True, text=True, timeout=120
        )
        assert completed.returncode == 0, completed.stdout + completed.stderr[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.page_status("fleet", str(i)) == "done" for i in range(1, 6))
        finally:
            store.close()
    finally:
        site.stop()


def test_ship_and_fleet_namespaces_coexist(tmp_path):
    site = FakeSite([97])
    add_fleet_routes(site, [97])
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, spider="ships_all")
        assert rc == 0, out[-3000:]
        rc, out = run_crawl(data, site.base_url, spider="fleets")
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            assert store.status(97) == "done"
            assert store.get_ship(97)["td_id"] == 97
            assert store.page_status("fleet", "97") == "done"
            assert store.get_fleet(97)["fleet_id"] == 97
        finally:
            store.close()
    finally:
        site.stop()
