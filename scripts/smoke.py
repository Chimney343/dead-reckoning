"""Live smoke test of the Three Decks scraper (Plan 6, layer 7).

    uv run python scripts/smoke.py [--pages 25 | --ships 100] [-s KEY=VALUE ...]

Runs the plan's Smoke tier: one captures query, Spain -> Great Britain, at the
normal 5 s rate. (A full captures crawl enumerates every nation, which is far too
slow to smoke.) By default it closes after ``--pages`` responses
(robots.txt and the captures POST count), about 3 minutes; ``--ships N`` closes
after N ship records instead (about 7 s per ship). It passes when the crawl was not
blocked, every item validated, no page failed to fetch or parse, at least one
capture row and one ship record came back, and no ship page had an unknown
section. Unknown base labels are listed but do not fail the run: add them to
``LABEL_CATEGORIES``.

Pages go into the normal cache and state database (``data/threedecks``), so
Tier A reuses them, and a second smoke run replays them from the cache without
touching the site. Unlike a full crawl, it does not wait out a 429 or a
Cloudflare challenge: it fails at once. Politeness settings can be overridden
only against a local test site (rule 1).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from scrapy import signals
from scrapy.crawler import CrawlerProcess
from scrapy.utils.defer import deferred_from_coro
from scrapy.utils.project import get_project_settings
from threedecks.items import CaptureRow, ShipRecord
from threedecks.lock import CrawlLock, CrawlLockHeld
from threedecks.politeness import parse_override, refusal_message, refused_overrides
from threedecks.ua import MISSING_CONTACT_HELP, contact

SPIDER = "captures"
SMOKE_FROM_NATION = 7   # Spain
SMOKE_BY_NATION = 1     # Great Britain
SHIP_LIMIT_REASON = "smoke_ship_limit"
OK_REASONS = {"finished", "closespider_pagecount", SHIP_LIMIT_REASON}


class ItemTally:
    """Counts the items the crawl yielded, by type; closes the crawl at ``ship_limit``."""

    def __init__(self, crawler=None, ship_limit: int | None = None) -> None:
        self.crawler = crawler
        self.ship_limit = ship_limit
        self.ships = 0
        self.captures = 0

    def on_item_scraped(self, item, response, spider) -> None:
        if isinstance(item, ShipRecord):
            self.ships += 1
            if self.ship_limit and self.ships == self.ship_limit:
                deferred_from_coro(self.crawler.engine.close_spider_async(reason=SHIP_LIMIT_REASON))
        elif isinstance(item, CaptureRow):
            self.captures += 1


def _with_prefix(stats: dict, prefix: str) -> dict[str, int]:
    return {k[len(prefix) :]: v for k, v in sorted(stats.items()) if k.startswith(prefix)}


def evaluate(
    stats: dict, ships: int, captures: int, ship_target: int | None = None
) -> tuple[list[str], list[str]]:
    """Return (failures, notes) for one smoke crawl. No failures means pass."""
    failures: list[str] = []
    reason = stats.get("finish_reason")
    if reason == "blocked":
        failures.append(
            "closed with reason 'blocked' (403, 429 or a Cloudflare challenge). Wait at "
            "least 15 minutes and rerun; if it is blocked again, stop and contact the "
            "site owner (rule 5)."
        )
    elif reason not in OK_REASONS:
        failures.append(f"closed with reason {reason!r}")
    for key, what in (
        ("item_dropped_count", "item(s) failed validation"),
        ("threedecks/fetch_error", "ship page(s) failed to fetch"),
        ("threedecks/parse_error", "ship page(s) raised in the parser"),
        ("threedecks/incomplete_page", "ship page(s) failed the completeness check"),
        ("log_count/ERROR", "error(s) logged; see the log above"),
    ):
        if stats.get(key):
            failures.append(f"{stats[key]} {what}")
    exceptions = sum(_with_prefix(stats, "spider_exceptions/").values())
    if exceptions:
        failures.append(f"{exceptions} spider exception(s)")
    if not captures:
        failures.append("no capture rows: the captures POST failed or its markup changed")
    if not ships:
        failures.append("no ship records")
    elif ship_target and ships < ship_target and reason != "finished":
        failures.append(f"only {ships} of {ship_target} ship records before the page cap")
    for section, count in _with_prefix(stats, "threedecks/unknown_section/").items():
        failures.append(f"unknown section {section!r} on {count} page(s)")

    notes: list[str] = []
    for label, count in _with_prefix(stats, "threedecks/unknown_label/").items():
        notes.append(f"unknown label {label!r} on {count} page(s); add it to LABEL_CATEGORIES")
    if stats.get("threedecks/not_found"):
        notes.append(
            f"{stats['threedecks/not_found']} ship id(s) from the captures list came back "
            "not found; check the not-found signature"
        )
    return failures, notes


def render(stats: dict, ships: int, captures: int, failures: list[str], notes: list[str]) -> str:
    responses = stats.get("response_received_count", 0)
    hits = stats.get("httpcache/hit", 0)
    lines = [
        f"Three Decks smoke test: {'FAIL' if failures else 'PASS'}",
        f"  closed     : {stats.get('finish_reason')}",
        f"  responses  : {responses} ({hits} from the cache, {responses - hits} from the network)",
        f"  items      : {captures} capture rows, {ships} ship records",
    ]
    lines += [f"  FAIL: {failure}" for failure in failures]
    lines += [f"  note: {note}" for note in notes]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--pages", type=int, default=None, help="responses before closing")
    parser.add_argument("--ships", type=int, default=None, help="ship records before closing")
    parser.add_argument(
        "-s", dest="settings", action="append", default=[], type=parse_override,
        metavar="KEY=VALUE", help="override a Scrapy setting",
    )
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(errors="replace")  # labels may not fit the console code page

    if not contact():
        print(f"error: {MISSING_CONTACT_HELP}", file=sys.stderr)
        return 2

    os.environ.setdefault("SCRAPY_SETTINGS_MODULE", "threedecks.settings")
    settings = get_project_settings()
    overrides = dict(args.settings)
    base_url = settings.get("THREEDECKS_BASE_URL")
    refused = refused_overrides(overrides, base_url)
    if refused:
        print(refusal_message(refused, base_url), file=sys.stderr)
        return 2
    settings.set("LOG_LEVEL", "INFO", priority="cmdline")
    settings.set("THREEDECKS_MAX_COOLOFFS", 0, priority="cmdline")  # fail fast
    settings.setdict(overrides, priority="cmdline")
    # With --ships, the page cap is only a backstop against a run of non-ship pages.
    pages = args.pages or (2 * args.ships + 10 if args.ships else 25)
    settings.set("CLOSESPIDER_PAGECOUNT", pages, priority="cmdline")

    data_dir = Path(settings["DATA_DIR"])
    try:
        # A smoke run during a crawl would double the request rate (threedecks.lock).
        with CrawlLock(data_dir / "crawl.lock"):
            process = CrawlerProcess(settings)
            crawler = process.create_crawler(SPIDER)
            tally = ItemTally(crawler, ship_limit=args.ships)
            crawler.signals.connect(tally.on_item_scraped, signal=signals.item_scraped)
            process.crawl(crawler, from_nation=SMOKE_FROM_NATION, by_nation=SMOKE_BY_NATION)
            process.start()
    except CrawlLockHeld as held:
        print(f"another crawl holds {data_dir} (pid {held.pid}, started {held.started}); "
              "its log and heartbeat live there", file=sys.stderr)
        return 2

    stats = crawler.stats.get_stats()
    failures, notes = evaluate(stats, tally.ships, tally.captures, ship_target=args.ships)
    print(render(stats, tally.ships, tally.captures, failures, notes))
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
