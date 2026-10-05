"""scripts/crawl_all.py: crawl.py sessions until every tier has finished.

crawl.py itself is replaced by fake sessions that change a real state database
the way a crawl would, so these tests only exercise the loop's decisions.
"""

from __future__ import annotations

import pytest
from threedecks.items import ShipRecord
from threedecks.state import StateStore

import scripts.crawl_all as crawl_all
from scripts.crawl import TIERS


def seed(data_dir, n):
    with StateStore(data_dir / "state.sqlite") as store:
        store.seed(range(1, n + 1), "sitemap")


def fetch(store, count, status="done"):
    """Move ``count`` pending ids to ``status``, storing a ship for each one done."""
    for td_id in list(store.pending_ids())[:count]:
        store.mark_status(td_id, status)
        if status == "done":
            store.save_ship(ShipRecord(td_id=td_id, name=f"Ship {td_id}"))


def close_run(store, spider, reason):
    store.finish_run(store.start_run(spider), close_reason=reason)


class FakeCrawl:
    """Plays one scripted session per call: ``(effect(store), exit code)``."""

    def __init__(self, data_dir, sessions):
        self.data_dir = data_dir
        self.sessions = list(sessions)
        self.calls: list[list[str]] = []

    def __call__(self, argv):
        self.calls.append(argv)
        effect, code = self.sessions.pop(0) if self.sessions else (None, 1)
        if effect:
            with StateStore(self.data_dir / "state.sqlite") as store:
                effect(store)
        return code


def finish_everything(store):
    fetch(store, 10_000)
    for spider in TIERS:
        close_run(store, spider, "finished")


def run(data_dir, fake, *argv):
    waits: list[float] = []
    code = crawl_all.main(
        list(argv), run_session=fake, wait=lambda minutes: waits.append(minutes) or True,
        data_dir=data_dir,
    )
    return code, waits


def test_sessions_run_until_every_tier_finishes_then_report_and_export(tmp_path):
    seed(tmp_path, 5)
    first = (lambda s: (fetch(s, 3), close_run(s, "ships_all", "ship_target")), 0)
    fake = FakeCrawl(tmp_path, [first, (finish_everything, 0)])

    code, waits = run(tmp_path, fake)

    assert code == 0
    assert len(fake.calls) == 2
    assert waits == []
    assert (tmp_path / "exports" / "ships.jsonl").read_text(encoding="utf-8").count("\n") == 5
    assert (tmp_path / "exports" / "qa_report.md").exists()


def test_each_session_adds_a_fixed_number_and_passes_options_through(tmp_path):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [(finish_everything, 0)])
    run(tmp_path, fake, "--session", "500", "--allow-sleep")
    assert fake.calls == [["--more", "500", "--allow-sleep"]]


def test_a_finished_crawl_only_reports(tmp_path):
    seed(tmp_path, 2)
    with StateStore(tmp_path / "state.sqlite") as store:
        finish_everything(store)
    fake = FakeCrawl(tmp_path, [])
    assert run(tmp_path, fake)[0] == 0
    assert fake.calls == []
    assert (tmp_path / "exports" / "ships.jsonl").exists()


def test_a_block_stops_for_good(tmp_path):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [(lambda s: (fetch(s, 1), close_run(s, "ships_all", "blocked")), 1)])
    code, waits = run(tmp_path, fake)
    assert code == 1
    assert len(fake.calls) == 1
    assert waits == []
    assert not (tmp_path / "exports").exists()


def test_an_incomplete_page_streak_stops_for_good(tmp_path):
    # Truncated pages or changed markup need a person and a smoke run, not a retry.
    seed(tmp_path, 5)
    streak = (lambda s: close_run(s, "ships_all", "incomplete_streak"), 1)
    fake = FakeCrawl(tmp_path, [streak, (finish_everything, 0)])
    code, waits = run(tmp_path, fake)
    assert code == 1
    assert len(fake.calls) == 1
    assert waits == []


@pytest.mark.parametrize("exit_code", [2, 130])  # refused to start; Ctrl+C
def test_a_refusal_or_ctrl_c_stops_at_once(tmp_path, exit_code):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [(None, exit_code)])
    assert run(tmp_path, fake) == (exit_code, [])
    assert len(fake.calls) == 1


def test_a_failed_session_is_retried_after_a_wait(tmp_path):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [(None, 1), (finish_everything, 0)])
    code, waits = run(tmp_path, fake)
    assert code == 0
    assert waits == [30]
    assert len(fake.calls) == 2


def test_failures_in_a_row_are_limited(tmp_path):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [])  # every session fails
    code, waits = run(tmp_path, fake, "--max-failures", "3")
    assert code == 1
    assert len(fake.calls) == 4
    assert waits == [30, 30, 30]


def test_a_session_that_mostly_fails_to_parse_stops_the_crawl(tmp_path):
    # A redesign, or a soft block served as a 200, would otherwise burn through
    # every id and fill the cache with pages the parser cannot read.
    seed(tmp_path, 100)
    bad = (lambda s: (fetch(s, 60, "parse_error"), fetch(s, 40)), 0)
    fake = FakeCrawl(tmp_path, [bad, (finish_everything, 0)])
    assert run(tmp_path, fake)[0] == 1
    assert len(fake.calls) == 1


def test_a_successful_session_without_progress_stops_the_loop(tmp_path):
    seed(tmp_path, 5)
    fake = FakeCrawl(tmp_path, [(None, 0), (finish_everything, 0)])
    assert run(tmp_path, fake)[0] == 1
    assert len(fake.calls) == 1
