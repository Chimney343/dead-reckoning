"""Layer 5: resume after a graceful stop, a hard kill, a truncation and a block.

The crawler runs in a subprocess against a local site. Only the one in-flight
page may ever be seen twice, and only after a hard kill.
"""

from __future__ import annotations

import json
import pickle
import sqlite3
import time
import zlib
from pathlib import Path

from resume_harness import FakeSite, run_crawl, start_crawl
from threedecks.state import StateStore

from scripts.export import main as export_main

IDS = list(range(1, 201))


def export_ship_ids(data_dir: Path) -> list[int]:
    out = data_dir / "exports"
    export_main(["--data-dir", str(data_dir), "--out", str(out)])
    lines = (out / "ships.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(line)["td_id"] for line in lines]


def assert_all_done(data_dir: Path):
    store = StateStore(data_dir / "state.sqlite")
    try:
        assert store.ship_count() == len(IDS)
        assert all(store.status(i) == "done" for i in IDS)
    finally:
        store.close()


def test_graceful_stop_then_resume(tmp_path):
    site = FakeSite(IDS).start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url, ["-s", "CLOSESPIDER_ITEMCOUNT=50"])
        assert rc == 0, out[-3000:]
        assert site.total_ship_requests >= 50

        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]

        assert_all_done(data)
        assert all(site.count(i) == 1 for i in IDS)
        ids = export_ship_ids(data)
        assert sorted(ids) == IDS
        assert len(set(ids)) == 200
    finally:
        site.stop()


def test_hard_kill_then_resume(tmp_path):
    site = FakeSite(IDS).start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        proc = start_crawl(data, site.base_url)
        deadline = time.time() + 60
        while site.total_ship_requests < 60 and proc.poll() is None and time.time() < deadline:
            time.sleep(0.05)
        if proc.poll() is None:
            proc.kill()
        proc.communicate()

        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]
        assert_all_done(data)

        counts = [site.count(i) for i in IDS]
        assert min(counts) >= 1
        assert max(counts) <= 2  # at most the one in-flight page is refetched
    finally:
        site.stop()


def corrupt_cached_ship(data_dir: Path, td_id: int) -> None:
    conn = sqlite3.connect(str(data_dir / "httpcache.sqlite"))
    try:
        for fingerprint, blob in conn.execute("SELECT fingerprint, data FROM responses"):
            payload = pickle.loads(zlib.decompress(blob))
            if f"id={td_id}" in (payload.get("url") or ""):
                payload["body"] = b"<html><head><title>Broken</title></head><body></body></html>"
                conn.execute(
                    "UPDATE responses SET data = ? WHERE fingerprint = ?",
                    (zlib.compress(pickle.dumps(payload, protocol=4)), fingerprint),
                )
        conn.commit()
    finally:
        conn.close()


def test_truncated_cache_entry_is_refetched(tmp_path):
    ids = list(range(1, 6))
    site = FakeSite(ids).start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]

        corrupt_cached_ship(data, 3)
        store = StateStore(data / "state.sqlite")
        with store._conn:  # noqa: SLF001 - simulate a record lost to a crash
            store._conn.execute("DELETE FROM ships WHERE td_id = 3")
            store._conn.execute("UPDATE frontier SET status = 'pending' WHERE td_id = 3")
        store.close()

        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            assert store.status(3) == "done"
            assert store.get_ship(3)["name"] == "Ship 3"
            assert store.ship_count() == len(ids)
        finally:
            store.close()
        assert site.count(3) >= 2  # the truncated page was refetched
    finally:
        site.stop()


def test_blocked_close_then_recover(tmp_path):
    ids = list(range(1, 21))
    site = FakeSite(ids)
    site.block_id = 10
    site.block_active = True
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            reason = store._conn.execute(  # noqa: SLF001
                "SELECT close_reason FROM runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()["close_reason"]
            assert reason == "blocked"
            assert store.status(10) != "done"
        finally:
            store.close()

        site.block_active = False
        rc, out = run_crawl(data, site.base_url)
        assert rc == 0, out[-3000:]
        store = StateStore(data / "state.sqlite")
        try:
            assert all(store.status(i) == "done" for i in ids)
        finally:
            store.close()
    finally:
        site.stop()


def test_rate_limit_is_waited_out_then_the_crawl_completes(tmp_path):
    ids = list(range(1, 21))
    site = FakeSite(ids)
    site.block_id, site.block_active, site.block_limit = 10, True, 1  # one 429, then fine
    site.start()
    data = tmp_path / "data"
    data.mkdir()
    try:
        cooloff = ["-s", "THREEDECKS_MAX_COOLOFFS=2", "-s", "THREEDECKS_COOLOFF_SECS=1"]
        rc, out = run_crawl(data, site.base_url, cooloff)
        assert rc == 0, out[-3000:]

        store = StateStore(data / "state.sqlite")
        try:
            reason = store._conn.execute(  # noqa: SLF001
                "SELECT close_reason FROM runs ORDER BY run_id DESC LIMIT 1"
            ).fetchone()["close_reason"]
            assert reason == "finished"
            assert all(store.status(i) == "done" for i in ids)
        finally:
            store.close()
        assert site.count(10) == 2  # the blocked request was retried once, unchanged
    finally:
        site.stop()
