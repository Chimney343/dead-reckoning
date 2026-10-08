"""Run the whole Three Decks crawl to the end, then write the QA report and exports.

    uv run python scripts/crawl_all.py [--session 2000] [--max-failures 3]
                                       [--failure-wait 30] [crawl.py options ...]

Runs ``crawl.py --more SESSION`` again and again, so each session gets a fresh
budget of stall restarts and network retries, until every tier has finished.
Between sessions it reads the state database and decides:

* a ``blocked`` close, Ctrl+C or a refusal to start stops for good (rule 5);
* an ``incomplete_streak`` close stops for good: truncated pages or changed
  markup need a person and a smoke run, not another fetch;
* a session that marks more than 5% of its pages ``parse_error`` stops: a site
  redesign or a soft block served as a 200 would otherwise run through every id;
* a successful session that settles no id stops, rather than loop forever;
* any other failure (stalls, a dead network, a crash) is retried after
  FAILURE_WAIT minutes, at most MAX_FAILURES times in a row.

Then it writes ``exports/qa_report.md`` and the exports. Rerun to resume.
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from pathlib import Path

from threedecks.settings import DATA_DIR
from threedecks.state import StateStore

import scripts.crawl as crawl
import scripts.export as export
import scripts.qa_report as qa_report

MAX_PARSE_ERROR_SHARE = 0.05
MIN_PAGES_FOR_SHARE = 20  # below this, a few odd pages say nothing about the site
UNSETTLED = ("pending", "error")  # error ids are retried until their attempts run out


def say(message: str) -> None:
    print(f"[crawl-all {time.strftime('%H:%M')}] {message}", flush=True)


def snapshot(data_dir: Path) -> tuple[int, int, int]:
    """(settled ids, parse errors, ships) in the frontier and ship table."""
    with StateStore(data_dir / "state.sqlite") as store:
        counts = store.counts_by_status()
        ships = store.ship_count()
    settled = sum(n for status, n in counts.items() if status not in UNSETTLED)
    return settled, counts.get("parse_error", 0), ships


def every_tier_finished(data_dir: Path) -> bool:
    return all(crawl.tier_finished(data_dir, spider) for spider in crawl.TIERS)


def last_close_reason(data_dir: Path) -> str | None:
    conn = sqlite3.connect(str(data_dir / "state.sqlite"))
    try:
        row = conn.execute("SELECT close_reason FROM runs ORDER BY run_id DESC LIMIT 1").fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def wait_minutes(minutes: float) -> bool:
    """Sleep; False if Ctrl+C."""
    try:
        time.sleep(minutes * 60)
    except KeyboardInterrupt:
        return False
    return True


def report_and_export(data_dir: Path) -> int:
    out = data_dir / "exports"
    out.mkdir(parents=True, exist_ok=True)
    qa_report.main(["--data-dir", str(data_dir), "--out", str(out / "qa_report.md")])
    return export.main(["--data-dir", str(data_dir), "--out", str(out)])


def main(argv=None, *, run_session=None, wait=None, data_dir: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--session", type=int, default=2000, help="ship records per session")
    parser.add_argument("--max-failures", type=int, default=3, help="failed sessions in a row")
    parser.add_argument("--failure-wait", type=float, default=30, help="minutes after a failure")
    args, passthrough = parser.parse_known_args(argv)
    if {"--ships", "--more"} & set(passthrough):
        parser.error("--ships and --more are set per session; use --session")
    run_session = run_session or crawl.main
    wait = wait or wait_minutes
    data_dir = Path(data_dir or DATA_DIR)

    failures = 0
    while not every_tier_finished(data_dir):
        settled, parse_errors, ships = snapshot(data_dir)
        code = run_session(["--more", str(args.session), *passthrough])
        new_settled, new_parse_errors, new_ships = snapshot(data_dir)
        moved = new_settled - settled
        say(f"session exited {code}: {moved} ids settled, {new_ships - ships:+d} ships, "
            f"{new_parse_errors - parse_errors} parse errors")

        if code in (2, 130):
            say("stopped: crawl.py refused to start or was interrupted")
            return code
        if moved >= MIN_PAGES_FOR_SHARE and (
            (new_parse_errors - parse_errors) / moved > MAX_PARSE_ERROR_SHARE
        ):
            say("stopped: too many pages failed to parse. Look at a cached page; the site "
                "may have changed or be serving a block page. Fix, reparse, then rerun.")
            return 1
        if code != 0:
            reason = last_close_reason(data_dir)
            if reason == "blocked":
                say("stopped: the site blocked the crawl (rule 5). Contact the owner first.")
                return 1
            if reason == "incomplete_streak":
                say("stopped: ship pages in a row failed the completeness check. "
                    "Run scripts/smoke.py and look at the pages before resuming.")
                return 1
            failures += 1
            if failures > args.max_failures:
                say(f"stopped: {failures} failed sessions in a row; see data/threedecks/logs/")
                return 1
            say(f"retrying in {args.failure_wait:g} min ({failures} of {args.max_failures})")
            if not wait(args.failure_wait):
                return 130
            continue
        failures = 0
        if moved == 0 and new_ships == ships and not every_tier_finished(data_dir):
            say("stopped: a session finished without settling any id")
            return 1

    say("every tier has finished; writing the QA report and exports")
    return report_and_export(data_dir)


if __name__ == "__main__":
    sys.exit(main())
