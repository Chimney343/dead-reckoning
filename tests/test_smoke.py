"""The smoke-test script (Plan 6, layer 7), run offline against a local site."""

from __future__ import annotations

import re
import subprocess
import sys

import pytest
from resume_harness import REPO_ROOT, FakeSite, crawl_env

import scripts.smoke as smoke

FAST = ["-s", "DOWNLOAD_DELAY=0", "-s", "AUTOTHROTTLE_ENABLED=False"]


def passing_stats(**extra):
    return {"finish_reason": "closespider_pagecount", **extra}


def test_clean_crawl_passes_and_lists_unknown_labels_as_notes():
    stats = passing_stats(**{"threedecks/unknown_label/Refloated By": 2})
    failures, notes = smoke.evaluate(stats, ships=3, captures=10)
    assert failures == []
    assert notes == ["unknown label 'Refloated By' on 2 page(s); add it to LABEL_CATEGORIES"]


@pytest.mark.parametrize(
    "stats,ships,captures,expected",
    [
        ({"finish_reason": "blocked"}, 3, 10, "rule 5"),
        ({"finish_reason": "shutdown"}, 3, 10, "'shutdown'"),
        (passing_stats(item_dropped_count=1), 3, 10, "failed validation"),
        (passing_stats(**{"threedecks/parse_error": 1}), 3, 10, "parser"),
        (passing_stats(**{"threedecks/incomplete_page": 1}), 3, 10, "completeness"),
        (passing_stats(**{"spider_exceptions/KeyError": 2}), 3, 10, "2 spider exception"),
        (passing_stats(**{"threedecks/unknown_section/Fate": 1}), 3, 10, "'Fate'"),
        (passing_stats(), 0, 10, "no ship records"),
        (passing_stats(), 3, 0, "no capture rows"),
    ],
)
def test_each_failure_is_reported(stats, ships, captures, expected):
    failures, _ = smoke.evaluate(stats, ships=ships, captures=captures)
    assert any(expected in failure for failure in failures), failures


def test_refuses_without_a_contact(monkeypatch, capsys):
    monkeypatch.delenv("THREEDECKS_CONTACT", raising=False)
    assert smoke.main([]) == 2
    assert "THREEDECKS_CONTACT" in capsys.readouterr().err


def test_refuses_to_loosen_the_rate_against_the_site(monkeypatch, capsys):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    monkeypatch.setattr(smoke, "CrawlerProcess", None)  # a crawl here would be a bug
    assert smoke.main(["-s", "DOWNLOAD_DELAY=0"]) == 2
    assert "rule 1" in capsys.readouterr().err


def run_smoke(site, data_dir, pages=6):
    return subprocess.run(
        [sys.executable, "scripts/smoke.py", "--pages", str(pages), *FAST],
        cwd=str(REPO_ROOT),
        env=crawl_env(data_dir, site.base_url),
        capture_output=True,
        text=True,
        timeout=240,
    )


def test_smoke_passes_against_a_healthy_site(tmp_path):
    site = FakeSite(range(1, 11)).start()
    try:
        result = run_smoke(site, tmp_path)
    finally:
        site.stop()
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    assert "smoke test: PASS" in result.stdout
    assert "10 capture rows" in result.stdout
    # 6 responses: robots.txt, the captures POST and 4 ship pages.
    assert site.total_ship_requests == 4


def test_smoke_fails_when_blocked(tmp_path):
    site = FakeSite(range(1, 11))
    site.block_id, site.block_active = 2, True
    site.start()
    try:
        result = run_smoke(site, tmp_path, pages=20)  # enough to reach every ship
    finally:
        site.stop()
    assert result.returncode == 1, result.stdout + result.stderr[-3000:]
    assert "smoke test: FAIL" in result.stdout
    assert "'blocked'" in result.stdout


def test_ship_limit_closes_after_that_many_ship_records(tmp_path):
    site = FakeSite(range(1, 21)).start()
    try:
        result = subprocess.run(
            [sys.executable, "scripts/smoke.py", "--ships", "5", *FAST],
            cwd=str(REPO_ROOT),
            env=crawl_env(tmp_path, site.base_url),
            capture_output=True,
            text=True,
            timeout=240,
        )
    finally:
        site.stop()
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    assert "closed     : smoke_ship_limit" in result.stdout
    # The page already in flight when the limit is reached still completes.
    ships = int(re.search(r"(\d+) ship records", result.stdout).group(1))
    assert ships in (5, 6)
    assert site.total_ship_requests == ships


def test_falling_short_of_the_ship_target_fails():
    failures, _ = smoke.evaluate(passing_stats(), ships=40, captures=10, ship_target=100)
    assert failures == ["only 40 of 100 ship records before the page cap"]
