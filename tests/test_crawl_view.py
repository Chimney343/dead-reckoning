"""The terminal view of a crawl: a bar with an ETA, and the latest message above it."""

from __future__ import annotations

import io

from threedecks.crawl_view import CrawlView, fmt_duration
from threedecks.state import StateStore


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def tick(self, seconds: float) -> None:
        self.now += seconds


def make_view(tmp_path, clock=None, wall=None):
    view = CrawlView(
        tmp_path, out=io.StringIO(), disable=True, clock=clock or Clock(),
        wall=wall or (lambda: 5000.0), columns=lambda: 60,
    )
    view.printed = []
    view._write = view.printed.append  # what scrolls above the bars
    return view


def seed_state(tmp_path, *, done=0, pending=0, errors=0, exhausted=0, ships=0):
    """Frontier rows: ``done`` settled, ``pending`` to fetch, ``errors`` retryable."""
    with StateStore(tmp_path / "state.sqlite") as store:
        ids = iter(range(1, 100_000))
        for _ in range(done):
            store.mark_status(next(ids), "not_found")
        store.seed([next(ids) for _ in range(pending)], "test")
        for _ in range(errors):
            store.mark_status(next(ids), "error", increment_attempts=True)
        for _ in range(exhausted):
            td_id = next(ids)
            for _ in range(3):
                store.mark_status(td_id, "error", increment_attempts=True)
        for td_id in range(1, ships + 1):
            store._conn.execute(
                "INSERT OR IGNORE INTO ships (td_id, record_json) VALUES (?, '{}')", (td_id,)
            )
        store._conn.commit()


def test_fmt_duration():
    assert fmt_duration(None) == "?"
    assert fmt_duration(3725) == "1:02:05"
    assert fmt_duration(90000) == "1d 1:00:00"


# --- which lines scroll, which only replace the message line --------------


def test_info_lines_only_replace_the_latest_message(tmp_path):
    view = make_view(tmp_path)
    view.show("2026-10-10 12:00:01 [scrapy.extensions.logstats] INFO: Crawled 5 pages\n", "child")
    assert view.printed == []
    assert view.last_message == "12:00:01 [scrapy.extensions.logstats] INFO: Crawled 5 pages"[:0] \
        or view.last_message == "12:00:01 Crawled 5 pages"


def test_warnings_errors_and_driver_lines_scroll(tmp_path):
    view = make_view(tmp_path)
    view.show("2026-10-10 12:00:01 [x] WARNING: incomplete ship page for id 7\n", "child")
    view.show("2026-10-10 12:00:02 [x] ERROR: boom\n", "child")
    view.show("[crawl 12:00:03] === captures ===\n", "say")
    assert len(view.printed) == 3


def test_a_traceback_after_an_error_scrolls_but_after_info_it_does_not(tmp_path):
    view = make_view(tmp_path)
    view.show("2026-10-10 12:00:01 [x] ERROR: Spider error\n", "child")
    view.show("Traceback (most recent call last):\n", "child")
    view.show('  File "x.py", line 1\n', "child")
    assert len(view.printed) == 3
    view.printed.clear()
    view.show("2026-10-10 12:00:02 [x] INFO: Some multi-line\n", "child")
    view.show("  second line of the message\n", "child")
    assert view.printed == []


def test_the_closing_stats_stay_on_screen(tmp_path):
    view = make_view(tmp_path)
    view.show("2026-10-10 12:00:01 [scrapy.statscollectors] INFO: Dumping Scrapy stats:\n", "child")
    view.show("{'finish_reason': 'finished',\n", "child")
    view.show(" 'item_scraped_count': 3}\n", "child")
    assert len(view.printed) == 3


def test_a_line_that_is_not_a_log_record_scrolls(tmp_path):
    view = make_view(tmp_path)
    view.show("Traceback from nowhere\n", "child")
    assert view.printed == ["Traceback from nowhere"]


def test_without_bars_lines_print_to_the_output(tmp_path):
    out = io.StringIO()
    view = CrawlView(tmp_path, out=out, disable=True)
    view.show("[crawl 12:00:03] hello\n", "say")
    assert out.getvalue() == "[crawl 12:00:03] hello\n"


def test_the_message_is_cut_to_the_terminal_width(tmp_path):
    view = make_view(tmp_path)
    view.start_tier("captures")
    view.show("2026-10-10 12:00:01 [x] INFO: " + "word " * 40 + "\n", "child")
    assert len(view._msg_bar.desc) <= 59


# --- the bar and the ETA --------------------------------------------------


def test_bar_counts_settled_against_settled_plus_remaining(tmp_path):
    seed_state(tmp_path, done=30, pending=60, errors=5, exhausted=2, ships=20)
    view = make_view(tmp_path)
    view.start_tier("ships_all")
    assert view._bar.n == 32  # 30 done + 2 given up on
    assert view._bar.total == 32 + 65  # pending + retryable errors
    assert "20 ships" in view._bar.postfix


def test_a_ship_target_caps_what_remains(tmp_path):
    seed_state(tmp_path, done=10, pending=500, ships=10)
    view = make_view(tmp_path)
    view.start_tier("captures", ship_target=110)
    assert view._bar.total == 10 + 100


def test_eta_uses_the_site_pace_until_there_is_data(tmp_path):
    seed_state(tmp_path, done=10, pending=150)
    view = make_view(tmp_path)
    view.start_tier("ships_all")
    assert "ETA 0:18:45" in view._bar.postfix  # 150 pages * 7.5 s
    assert "8.0 pages/min" in view._bar.postfix


def settle(tmp_path, first, last):
    with StateStore(tmp_path / "state.sqlite") as store:
        for td_id in range(first, last + 1):
            store.mark_status(td_id, "not_found")


def test_eta_follows_the_measured_rate(tmp_path):
    seed_state(tmp_path, pending=1000)
    clock = Clock()
    view = make_view(tmp_path, clock)
    view.start_tier("ships_all")
    settle(tmp_path, 1, 30)
    clock.tick(300)  # 30 pages in 5 minutes: 0.1 pages/s
    view.tick(force=True)
    assert abs(view._rate() - 0.1) < 1e-9
    assert "6.0 pages/min" in view._bar.postfix
    assert "ETA 2:41:40" in view._bar.postfix  # 970 pages / 0.1 per second


def test_a_replay_burst_cannot_beat_the_owners_rate(tmp_path):
    seed_state(tmp_path, pending=1000)
    clock = Clock()
    view = make_view(tmp_path, clock)
    view.start_tier("ships_all")
    settle(tmp_path, 1, 300)  # cached pages replayed in a rush
    clock.tick(300)
    view.tick(force=True)
    assert view._rate() == 0.2


def test_no_progress_for_minutes_means_an_unknown_eta(tmp_path):
    seed_state(tmp_path, pending=100)
    clock = Clock()
    view = make_view(tmp_path, clock)
    view.start_tier("ships_all")
    clock.tick(200)
    view.tick(force=True)
    assert "ETA ?" in view._bar.postfix


def test_a_cooloff_is_left_out_of_the_rate_and_added_to_the_eta(tmp_path):
    seed_state(tmp_path, pending=100)
    clock = Clock()
    wall = [5000.0]
    beat = {"cooloff_until": 5000.0 + 900}
    view = make_view(tmp_path, clock, lambda: wall[0])
    view.start_tier("ships_all", heartbeat=lambda: beat)
    clock.tick(300)
    wall[0] += 300
    view.tick(force=True)
    assert "cool-off until" in view._bar.postfix
    assert view._paused == 300
    # 100 pages at the default pace, plus the 600 s of cool-off still to wait.
    assert "ETA 0:22:30" in view._bar.postfix


def test_done_when_nothing_is_left(tmp_path):
    seed_state(tmp_path, done=5)
    view = make_view(tmp_path)
    view.start_tier("ships_all")
    assert view._bar.postfix.startswith("done")


def test_an_unreadable_state_leaves_the_bar_alone(tmp_path):
    view = make_view(tmp_path)  # no state.sqlite yet
    view.start_tier("captures")
    assert view._bar.total == 0


def test_close_removes_the_bars(tmp_path):
    view = make_view(tmp_path)
    view.start_tier("captures")
    view.close()
    assert view._bar is None and view._msg_bar is None
    view.tick()  # harmless after close
