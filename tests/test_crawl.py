"""scripts/crawl.py: tiers in order until the database holds N ships."""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import time
from types import SimpleNamespace

import pytest
from resume_harness import REPO_ROOT, FakeSite, crawl_env

import scripts.crawl as crawl

FAST = [
    "-s", "DOWNLOAD_DELAY=0",
    "-s", "AUTOTHROTTLE_ENABLED=False",
    "-s", "THREEDECKS_UPWARD_LIMIT=1",
    "-s", "THREEDECKS_MAX_COOLOFFS=0",
]


def run(site, data_dir, *args):
    return subprocess.run(
        [sys.executable, "scripts/crawl.py", "--pause-seconds", "0", *args, *FAST],
        cwd=str(REPO_ROOT),
        env=crawl_env(data_dir, site.base_url),
        capture_output=True,
        text=True,
        timeout=240,
    )


def spiders_run(data_dir):
    conn = sqlite3.connect(data_dir / "state.sqlite")
    try:
        return [row[0] for row in conn.execute("SELECT spider FROM runs ORDER BY run_id")]
    finally:
        conn.close()


def ships_stored(data_dir):
    conn = sqlite3.connect(data_dir / "state.sqlite")
    try:
        return conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0]
    finally:
        conn.close()


def test_refuses_without_a_contact(monkeypatch, capsys):
    monkeypatch.delenv("THREEDECKS_CONTACT", raising=False)
    assert crawl.main([]) == 2
    assert "THREEDECKS_CONTACT" in capsys.readouterr().err


def test_refuses_to_loosen_the_rate_against_the_site(monkeypatch, capsys):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    monkeypatch.setattr(crawl, "THREEDECKS_BASE_URL", "https://threedecks.org")
    monkeypatch.setattr(crawl, "run_tier", None)  # a crawl here would be a bug
    assert crawl.main(["-s", "DOWNLOAD_DELAY=1"]) == 2
    assert "rule 1" in capsys.readouterr().err


def test_rejects_an_unknown_tier():
    with pytest.raises(SystemExit):
        crawl.main(["--tiers", "captures,officers"])


# --- extra tiers (actions, fleets): shared driver, separate settings -------------


def _fake_args(**overrides):
    values = dict(
        ships=50, more=None, allow_sleep=True, daily_pages=0,
        day_start="00:00", rerun=False, pause_seconds=0.0,
        stall_minutes=crawl.STALL_SECS / 60, watch_seconds=crawl.WATCH_SECS,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_extra_tier_is_accepted_and_the_default_is_unchanged(monkeypatch, tmp_path):
    monkeypatch.setattr(crawl, "EXTRA_TIERS", ("dummy",))
    monkeypatch.setenv("THREEDECKS_CONTACT", "test@example.org")
    monkeypatch.setattr(crawl, "THREEDECKS_BASE_URL", "http://127.0.0.1:9")
    monkeypatch.setattr(crawl, "DATA_DIR", tmp_path)
    seen = {}

    def fake_crawl(args, tiers, *rest, **kwargs):
        seen["tiers"] = tiers
        return 0

    monkeypatch.setattr(crawl, "crawl", fake_crawl)

    assert crawl.main(["--tiers", "dummy"]) == 0
    assert seen["tiers"] == ["dummy"]
    assert crawl.main([]) == 0
    assert seen["tiers"] == list(crawl.TIERS)


def test_an_unknown_tier_is_rejected_even_with_extra_tiers(monkeypatch):
    monkeypatch.setattr(crawl, "EXTRA_TIERS", ("dummy",))
    with pytest.raises(SystemExit):
        crawl.main(["--tiers", "captures,dummy,officers"])


def test_an_extra_tier_runs_below_any_ship_target(monkeypatch, tmp_path):
    """An extra tier is not skipped by the ship target, and its command carries
    no THREEDECKS_SHIP_TARGET (S1)."""
    monkeypatch.setattr(crawl, "EXTRA_TIERS", ("dummy",))
    commands: list[list[str]] = []

    def fake_run_tier(spider, target, overrides, data_dir, log, **kwargs):
        commands.append(crawl.tier_command(spider, target, overrides))
        return crawl.TierResult(code=0)

    monkeypatch.setattr(crawl, "run_tier", fake_run_tier)
    monkeypatch.setattr(crawl, "tier_finished", lambda data_dir, spider: None)
    monkeypatch.setattr(crawl, "last_run", lambda data_dir, spider: {"close_reason": "finished"})
    monkeypatch.setattr(crawl, "ship_count", lambda data_dir: 9999)  # above the target

    log = crawl.Log(tmp_path / "log.txt")
    try:
        assert crawl.crawl(_fake_args(ships=50), ["dummy"], [], {}, tmp_path, log) == 0
    finally:
        log.close()

    assert len(commands) == 1
    assert not any(arg.startswith("THREEDECKS_SHIP_TARGET=") for arg in commands[0])
    # A ship tier still carries the target.
    ship_command = crawl.tier_command("captures", 50, {})
    assert any(arg == "THREEDECKS_SHIP_TARGET=50" for arg in ship_command)


def test_a_page_cap_close_ends_the_chain_cleanly(monkeypatch, tmp_path):
    monkeypatch.setattr(crawl, "run_tier", lambda *a, **k: crawl.TierResult(code=0))
    monkeypatch.setattr(crawl, "tier_finished", lambda data_dir, spider: None)
    monkeypatch.setattr(
        crawl, "last_run", lambda data_dir, spider: {"close_reason": "closespider_pagecount"}
    )
    monkeypatch.setattr(crawl, "ship_count", lambda data_dir: 0)

    log = crawl.Log(tmp_path / "log.txt")
    try:
        assert crawl.crawl(_fake_args(), ["actions"], [], {}, tmp_path, log) == 0
    finally:
        log.close()
    assert "page cap reached during actions" in (tmp_path / "log.txt").read_text(encoding="utf-8")


def test_stops_at_the_target_and_a_rerun_does_nothing(tmp_path):
    site = FakeSite(range(1, 21)).start()
    try:
        result = run(site, tmp_path, "--ships", "5", "--tiers", "captures,ships_all")
        assert result.returncode == 0, result.stdout + result.stderr[-3000:]
        assert "target of 5 reached during captures" in result.stdout
        assert ships_stored(tmp_path) in (5, 6)  # plus the page in flight, at most
        assert spiders_run(tmp_path) == ["captures"]  # Tier C never started

        fetched = site.total_ship_requests
        again = run(site, tmp_path, "--ships", "5", "--tiers", "captures,ships_all")
        assert again.returncode == 0
        assert "target of 5 reached." in again.stdout
        assert site.total_ship_requests == fetched

        # A higher target: the ships already stored are replayed from the cache and
        # re-saved, which must not count twice.
        more = run(site, tmp_path, "--ships", "9", "--tiers", "captures,ships_all")
        assert more.returncode == 0, more.stdout + more.stderr[-3000:]
        assert ships_stored(tmp_path) in (9, 10)
    finally:
        site.stop()


def test_moves_to_the_next_tier_when_one_runs_out(tmp_path):
    site = FakeSite(range(1, 11)).start()
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures,ships_all")
    finally:
        site.stop()
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    assert spiders_run(tmp_path) == ["captures", "ships_all"]
    assert "every tier finished below the target of 50" in result.stdout
    assert ships_stored(tmp_path) == 10


def test_a_block_stops_the_chain(tmp_path):
    site = FakeSite(range(1, 11))
    site.block_id, site.block_active = 5, True
    site.start()
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures,ships_all")
    finally:
        site.stop()
    assert result.returncode == 1, result.stdout + result.stderr[-3000:]
    assert "Rule 5" in result.stdout
    assert "notification:" in result.stdout
    assert spiders_run(tmp_path) == ["captures"]  # Tier C was not started against a block


def test_more_adds_that_many_to_what_is_stored(tmp_path):
    site = FakeSite(range(1, 21)).start()
    try:
        first = run(site, tmp_path, "--more", "4", "--tiers", "captures")
        assert first.returncode == 0, first.stdout + first.stderr[-3000:]
        after_first = ships_stored(tmp_path)
        assert after_first in (4, 5)

        second = run(site, tmp_path, "--more", "4", "--tiers", "captures")
        assert second.returncode == 0, second.stdout + second.stderr[-3000:]
        assert f"target {after_first + 4}" in second.stdout
        assert ships_stored(tmp_path) in (after_first + 4, after_first + 5)
    finally:
        site.stop()


def test_ships_and_more_are_exclusive():
    with pytest.raises(SystemExit):
        crawl.main(["--ships", "10", "--more", "5"])


# --- watchdog, keep-awake, logs, skipping, network outages -------------------


def test_watchdog_reports_a_suspended_pc_and_gives_grace_after_waking():
    dog = crawl.Watchdog(now=0, stall_secs=1200)
    assert dog.look(30, {"responses": 5}) is None
    kind, gap = dog.look(30 + 4 * 3600, {"responses": 5})  # slept 4 h
    assert (kind, gap) == ("suspended", 4 * 3600)
    assert dog.look(30 + 4 * 3600 + 30, {"responses": 5}) is None  # grace, not a stall


def test_watchdog_reports_a_stall_but_not_during_a_cooloff():
    dog = crawl.Watchdog(now=0, stall_secs=1200)
    # The first beat (t=30) is the last progress; nothing new for 20 min after it.
    events = [dog.look(t, {"responses": 7}) for t in range(30, 1261, 30)]
    assert events[:-1] == [None] * (len(events) - 1)
    assert events[-1] == ("stalled", 1230)

    dog = crawl.Watchdog(now=0, stall_secs=1200)
    t = 0
    for _ in range(80):  # 40 min paused for Cloudflare
        t += 30
        assert dog.look(t, {"responses": 7, "cooloff_until": 3600}) is None


def test_watchdog_progress_resets_the_stall_clock():
    dog = crawl.Watchdog(now=0, stall_secs=1200)
    for t in range(30, 3600, 30):
        assert dog.look(t, {"responses": t}) is None


def test_keep_awake_is_released_and_can_be_turned_off():
    with crawl.keep_awake(False) as awake:
        assert awake is False
    with crawl.keep_awake(True) as awake:
        assert awake is (sys.platform == "win32")


def test_finished_tiers_are_skipped_and_everything_is_logged(tmp_path):
    site = FakeSite(range(1, 6)).start()
    try:
        first = run(site, tmp_path, "--ships", "50", "--tiers", "captures")
        assert first.returncode == 0, first.stdout + first.stderr[-3000:]
        fetched = site.total_ship_requests

        again = run(site, tmp_path, "--ships", "50", "--tiers", "captures")
        assert "skipping captures: it finished at" in again.stdout
        assert spiders_run(tmp_path) == ["captures"]  # no second run

        replay = run(site, tmp_path, "--ships", "50", "--tiers", "captures", "--rerun")
        assert spiders_run(tmp_path) == ["captures", "captures"]
        assert site.total_ship_requests == fetched  # replayed from the cache
    finally:
        site.stop()
    logs = sorted((tmp_path / "logs").glob("crawl-*.log"))
    assert logs, "no log file written"
    text = "\n".join(path.read_text(encoding="utf-8") for path in logs)
    assert "=== captures ===" in text
    assert "Spider closed (finished)" in text  # Scrapy's own output, not only the driver's
    assert replay.returncode == 0


def test_a_dead_network_is_retried_without_charging_attempts(tmp_path):
    site = FakeSite(range(1, 11))
    site.drop_ships = True
    site.start()
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures",
                     "--network-waits", "0.001")
    finally:
        site.stop()
    assert result.returncode == 1, result.stdout + result.stderr[-3000:]
    assert "retrying captures in 0.001 min (1 of 1)" in result.stdout
    assert "the network stayed down through every retry" in result.stdout
    conn = sqlite3.connect(tmp_path / "state.sqlite")
    try:
        attempts = conn.execute("SELECT MAX(attempts) FROM frontier").fetchone()[0]
        reasons = [r[0] for r in conn.execute("SELECT close_reason FROM runs ORDER BY run_id")]
    finally:
        conn.close()
    assert attempts == 0  # an outage does not use up the pages' retries
    assert reasons == ["network_down", "network_down"]


# --- the watchdog against a real crawl process (the 2026-10-04 false stall) ---

QUICK_WATCHDOG = [
    "--stall-minutes", "0.05",  # 3 s without a new response
    "--watch-seconds", "0.5",
    "-s", "THREEDECKS_HEARTBEAT_SECS=0.2",
]


def test_a_healthy_crawl_is_not_stopped_by_the_watchdog(tmp_path):
    # On Windows the venv python.exe is a launcher, so the crawl runs under a
    # different process id; the watchdog must still recognise its heartbeat.
    site = FakeSite(range(1, 31))
    site.hang_secs = 0.2  # slow enough that the crawl outlives the stall window
    site.start()
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures", *QUICK_WATCHDOG)
    finally:
        site.stop()
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    assert "no new response" not in result.stdout
    assert "no heartbeat" not in result.stdout
    assert ships_stored(tmp_path) == 30


def test_a_hung_crawl_is_stopped_and_restarted(tmp_path):
    site = FakeSite(range(1, 6))
    site.hang_secs = 30  # ship pages never arrive within the stall window
    site.start()
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures", *QUICK_WATCHDOG)
    finally:
        site.stop()
    assert result.returncode == 1, result.stdout + result.stderr[-3000:]
    assert result.stdout.count("no new response") == 3
    assert "restarting captures (2 of 2)" in result.stdout
    assert "kept stalling" in result.stdout


def test_watchdog_never_stops_a_crawl_it_has_not_heard_from():
    dog = crawl.Watchdog(now=0, stall_secs=60)
    events = [dog.look(t, None) for t in range(30, 3600, 30)]
    assert ("no_heartbeat", 330) in events  # warns once, after 5 min
    assert [e for e in events if e] == [("no_heartbeat", 330)]  # and never "stalled"


# --- daily budget and crawl window helpers -------------------------------------


def local_ts(year, month, day, hour, minute):
    return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))


def test_parse_window_accepts_same_day_and_overnight():
    assert crawl.parse_window("09:00-17:30") == (9 * 60, 17 * 60 + 30)
    assert crawl.parse_window("22:00-06:00") == (22 * 60, 6 * 60)


@pytest.mark.parametrize(
    "text", ["nine-five", "09:00", "09:00-17:00-18:00", "25:00-26:00", "09:00-09:05"]
)
def test_parse_window_rejects_bad_values(text):
    with pytest.raises(ValueError):
        crawl.parse_window(text)


def test_rejects_a_bad_window_flag():
    with pytest.raises(SystemExit):
        crawl.main(["--window", "22:00-22:05"])


def test_window_wait_seconds_inside_outside_and_overnight():
    window = crawl.parse_window("09:00-17:30")
    assert crawl.window_wait_seconds(local_ts(2026, 10, 5, 12, 0), window) == 0.0
    before = local_ts(2026, 10, 5, 7, 0)
    assert crawl.window_wait_seconds(before, window) == local_ts(2026, 10, 5, 9, 0) - before
    after = local_ts(2026, 10, 5, 18, 0)
    assert crawl.window_wait_seconds(after, window) == local_ts(2026, 10, 6, 9, 0) - after

    overnight = crawl.parse_window("22:00-06:00")
    assert crawl.window_wait_seconds(local_ts(2026, 10, 5, 23, 0), overnight) == 0.0
    assert crawl.window_wait_seconds(local_ts(2026, 10, 6, 5, 0), overnight) == 0.0
    noon = local_ts(2026, 10, 6, 12, 0)
    assert crawl.window_wait_seconds(noon, overnight) == local_ts(2026, 10, 6, 22, 0) - noon


def test_next_day_start_is_today_or_tomorrow():
    today = crawl.next_day_start(local_ts(2026, 10, 5, 5, 0), "06:00")
    assert today == local_ts(2026, 10, 5, 6, 0)
    tomorrow = crawl.next_day_start(local_ts(2026, 10, 5, 7, 0), "06:00")
    assert tomorrow == local_ts(2026, 10, 6, 6, 0)


def test_window_end_epoch_wraps_overnight():
    overnight = crawl.parse_window("22:00-06:00")
    late = crawl.window_end_epoch(local_ts(2026, 10, 5, 23, 0), overnight)
    assert late == local_ts(2026, 10, 6, 6, 0)
    early = crawl.window_end_epoch(local_ts(2026, 10, 6, 5, 0), overnight)
    assert early == local_ts(2026, 10, 6, 6, 0)


def test_pages_today_sums_runs_since_the_day_boundary(tmp_path):
    from threedecks.state import StateStore, utc_iso

    now = local_ts(2026, 10, 5, 12, 0)
    boundary = crawl.day_start_epoch(now, "00:00")
    store = StateStore(tmp_path / "state.sqlite")
    with store._conn:  # noqa: SLF001
        store._conn.executemany(  # noqa: SLF001
            "INSERT INTO runs (spider, started_at, pages_fetched) VALUES (?, ?, ?)",
            [
                ("captures", utc_iso(boundary - 3600), 100),  # before the boundary
                ("captures", utc_iso(boundary + 60), 40),
                ("ships_all", utc_iso(boundary + 7200), 25),
            ],
        )
    store.close()
    assert crawl.pages_today(tmp_path, "00:00", now=now) == 65


def test_daily_budget_waits_for_the_boundary_and_resumes(tmp_path):
    # Two ships and a budget of 4: run 1 fetches everything, closes 'daily_budget',
    # waits for the boundary, then replays it all from the cache and finishes.
    site = FakeSite(range(1, 3)).start()
    day_start = time.strftime("%H:%M", time.localtime(time.time() + 120))
    try:
        result = run(site, tmp_path, "--ships", "50", "--tiers", "captures",
                     "--daily-pages", "4", "--day-start", day_start)
    finally:
        site.stop()
    assert result.returncode == 0, result.stdout + result.stderr[-3000:]
    assert "daily budget reached; waiting until" in result.stdout
    conn = sqlite3.connect(tmp_path / "state.sqlite")
    try:
        reasons = [row[0] for row in conn.execute("SELECT close_reason FROM runs ORDER BY run_id")]
    finally:
        conn.close()
    assert reasons == ["daily_budget", "finished"]
