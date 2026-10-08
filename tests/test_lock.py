"""threedecks/lock.py: one crawl per data dir (anti-bot review 2026-10-04).

Two crawl.py processes over the same data/threedecks would fetch the same
pending ids, doubling the request rate against the owner's 5 s condition.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time

import pytest
from resume_harness import REPO_ROOT, FakeSite, crawl_env
from threedecks.lock import CrawlLock, CrawlLockHeld, holder

FAST = [
    "-s", "DOWNLOAD_DELAY=0",
    "-s", "AUTOTHROTTLE_ENABLED=False",
    "-s", "THREEDECKS_UPWARD_LIMIT=1",
    "-s", "THREEDECKS_MAX_COOLOFFS=0",
]


def test_second_acquire_in_the_same_process_fails(tmp_path):
    path = tmp_path / "crawl.lock"
    with CrawlLock(path) as lock:
        assert lock._fd is not None  # noqa: SLF001
        with pytest.raises(CrawlLockHeld) as excinfo:
            with CrawlLock(path):
                pass
        assert excinfo.value.pid == str(os.getpid())


def test_release_allows_reacquiring(tmp_path):
    path = tmp_path / "crawl.lock"
    with CrawlLock(path):
        pass
    with CrawlLock(path):  # the OS released it when the first block ended
        pass


def test_holder_info_is_readable_while_held(tmp_path):
    path = tmp_path / "crawl.lock"
    with CrawlLock(path):
        pid, started = holder(path)
        assert pid == str(os.getpid())
        assert started[:2] == "20"  # local ISO date


def test_holder_info_is_graceful_for_a_junk_file(tmp_path):
    path = tmp_path / "crawl.lock"
    path.write_bytes(b"\x00")
    assert holder(path) == ("?", "?")


def run(site, data_dir, *args):
    return subprocess.run(
        [sys.executable, "scripts/crawl.py", "--pause-seconds", "0", *args, *FAST],
        cwd=str(REPO_ROOT),
        env=crawl_env(data_dir, site.base_url),
        capture_output=True,
        text=True,
        timeout=240,
    )


def test_a_second_crawl_exits_2(tmp_path):
    site = FakeSite(range(1, 11))
    site.hang_secs = 1.5  # the first crawl outlives the second's startup
    site.start()
    first = subprocess.Popen(
        [sys.executable, "scripts/crawl.py", "--pause-seconds", "0",
         "--ships", "50", "--tiers", "captures", *FAST],
        cwd=str(REPO_ROOT),
        env=crawl_env(tmp_path, site.base_url),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        # Once the first crawl fetches, it holds the lock (acquired before the tier).
        deadline = time.time() + 60
        while site.total_ship_requests == 0:
            assert time.time() < deadline, "the first crawl never fetched a ship page"
            time.sleep(0.2)

        second = run(site, tmp_path, "--ships", "50", "--tiers", "captures")
        assert second.returncode == 2, second.stdout + second.stderr[-3000:]
        assert "another crawl holds" in second.stdout
        assert str(tmp_path) in second.stdout

        out, _ = first.communicate(timeout=120)
        assert first.returncode == 0, out[-3000:]
    finally:
        if first.poll() is None:
            first.kill()
            first.wait(timeout=30)
        site.stop()
