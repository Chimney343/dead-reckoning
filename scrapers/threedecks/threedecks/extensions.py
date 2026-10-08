"""Crawl extensions: a ship-count target, a heartbeat, and a daily budget.

ShipTarget closes a crawl once the state database holds enough ship records.

``THREEDECKS_SHIP_TARGET`` counts records in ``state.sqlite``, not pages fetched
in this run: a re-saved record (a page replayed from the cache) does not count
twice, and a resumed crawl stops at the same total. The page in flight when the
target is reached still completes, so a run can end one or two records over.

CrawlBudget closes a crawl at ``THREEDECKS_DAILY_PAGES`` live fetches or at
``THREEDECKS_STOP_AT``; scripts/crawl.py sets both per tier and waits at the
boundary, so an unattended multi-day run keeps to a daily page budget and an
allowed time window without a page cap.
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path

from scrapy import signals
from scrapy.exceptions import NotConfigured
from scrapy.utils.defer import deferred_from_coro

from threedecks.items import ShipRecord
from threedecks.state import StateStore

logger = logging.getLogger(__name__)

SHIP_TARGET_REASON = "ship_target"
DAILY_BUDGET_REASON = "daily_budget"
WINDOW_CLOSED_REASON = "window_closed"
HEARTBEAT_FILE = "heartbeat.json"


class ShipTarget:
    def __init__(self, crawler, target: int) -> None:
        self.crawler = crawler
        self.target = target
        self.store: StateStore | None = None
        self.closing = False

    @classmethod
    def from_crawler(cls, crawler):
        target = crawler.settings.getint("THREEDECKS_SHIP_TARGET")
        if target <= 0:
            raise NotConfigured
        extension = cls(crawler, target)
        crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(extension.item_scraped, signal=signals.item_scraped)
        crawler.signals.connect(extension.spider_closed, signal=signals.spider_closed)
        return extension

    def spider_opened(self, spider) -> None:
        # The same file StatePipeline writes to.
        self.store = StateStore(Path(self.crawler.settings["DATA_DIR"]) / "state.sqlite")

    def item_scraped(self, item, spider) -> None:
        if self.closing or not isinstance(item, ShipRecord) or self.store is None:
            return
        count = self.store.ship_count()
        if count >= self.target:
            self.closing = True
            logger.info("%d ship records stored; target %d reached", count, self.target)
            deferred_from_coro(self.crawler.engine.close_spider_async(reason=SHIP_TARGET_REASON))

    def spider_closed(self, spider) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None


class CrawlBudget:
    """Close a crawl at ``THREEDECKS_DAILY_PAGES`` live pages or at ``THREEDECKS_STOP_AT``.

    scripts/crawl.py passes the remaining daily budget and the window's end to
    each tier and waits at the boundary before rerunning it. A cache replay is
    not a live fetch and does not count; robots.txt does (accepted slop).
    """

    def __init__(self, crawler, daily_pages: int, stop_at: float) -> None:
        self.crawler = crawler
        self.daily_pages = daily_pages
        self.stop_at = stop_at
        self.count = 0
        self.closing = False

    @classmethod
    def from_crawler(cls, crawler):
        daily_pages = crawler.settings.getint("THREEDECKS_DAILY_PAGES", 0)
        stop_at = crawler.settings.getfloat("THREEDECKS_STOP_AT", 0.0)
        if daily_pages <= 0 and stop_at <= 0:
            raise NotConfigured  # off by default: no budget, no window
        extension = cls(crawler, daily_pages, stop_at)
        crawler.signals.connect(extension.response_received, signal=signals.response_received)
        return extension

    def response_received(self, response, request, spider) -> None:
        if self.closing or request.meta.get("cache_timestamp"):
            return
        self.count += 1
        if 0 < self.daily_pages <= self.count:
            self.close(DAILY_BUDGET_REASON, f"daily budget of {self.daily_pages} pages reached")
        elif 0 < self.stop_at <= time.time():
            self.close(WINDOW_CLOSED_REASON, "the crawl window has closed")

    def close(self, reason: str, message: str) -> None:
        self.closing = True
        logger.info("%s; closing spider with reason '%s'", message, reason)
        deferred_from_coro(self.crawler.engine.close_spider_async(reason=reason))


class Heartbeat:
    """Write ``heartbeat.json`` every 30 s for the watchdog in scripts/crawl.py.

    It says how many responses the crawl has had and whether it is in a
    Cloudflare cool-off, so the watchdog can tell a stalled crawl from a paused
    one. The file is replaced atomically; a beat that cannot write is skipped.
    """

    interval = 30.0

    log_interval = 60.0

    def __init__(self, crawler, path: Path) -> None:
        self.crawler = crawler
        self.path = path
        self.loop = None
        self.token = crawler.settings.get("THREEDECKS_RUN_TOKEN")
        self.interval = crawler.settings.getfloat("THREEDECKS_HEARTBEAT_SECS", 30.0)
        self._logged_at: float | None = None
        self._logged_site = 0

    @classmethod
    def from_crawler(cls, crawler):
        data_dir = crawler.settings.get("DATA_DIR")
        if not crawler.settings.getbool("THREEDECKS_HEARTBEAT", True) or not data_dir:
            raise NotConfigured
        extension = cls(crawler, Path(data_dir) / HEARTBEAT_FILE)
        crawler.signals.connect(extension.spider_opened, signal=signals.spider_opened)
        crawler.signals.connect(extension.spider_closed, signal=signals.spider_closed)
        return extension

    def spider_opened(self, spider) -> None:
        from twisted.internet import task

        self.loop = task.LoopingCall(self.beat)
        self.loop.start(self.interval, now=True)

    def spider_closed(self, spider, reason) -> None:
        if self.loop is not None and self.loop.running:
            self.loop.stop()
        self.beat(closed=reason)

    def beat(self, closed: str | None = None) -> None:
        stats = self.crawler.stats
        spider = getattr(self.crawler, "spider", None)
        cached = stats.get_value("httpcache/hit", 0) or 0
        site = (stats.get_value("response_received_count", 0) or 0) - cached
        self._log_rate(site, cached, final=closed is not None)
        data = {
            "token": self.token,
            "pid": os.getpid(),
            "spider": getattr(spider, "name", None),
            "at": time.time(),
            "responses": stats.get_value("response_received_count", 0),
            "cache_hits": stats.get_value("httpcache/hit", 0),
            "items": stats.get_value("item_scraped_count", 0),
            "cooloff_until": stats.get_value("threedecks/cooloff_until"),
            "closed": closed,
        }
        tmp = self.path.with_suffix(".tmp")
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps(data), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError:  # e.g. the watchdog has it open on Windows; next beat
            logger.debug("heartbeat not written", exc_info=True)

    def _log_rate(self, site: int, cached: int, final: bool = False) -> None:
        """Log what went to the site, apart from cache replays. Scrapy's own
        "pages/min" counts both, so a replay burst looks like a breach of rule 1."""
        now = time.time()
        if self._logged_at is None:
            self._logged_at, self._logged_site = now, site
            return
        if not final and now - self._logged_at < self.log_interval:
            return
        minutes = max((now - self._logged_at) / 60, 1e-9)
        logger.info(
            "pages from the site: %d (%.1f/min since the last report); from the cache: %d",
            site, (site - self._logged_site) / minutes, cached,
        )
        self._logged_at, self._logged_site = now, site
