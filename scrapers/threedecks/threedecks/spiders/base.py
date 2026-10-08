"""Shared spider behaviour (Plan 4, 5).

A spider only builds requests and calls the pure parsers. Progress is read from
and written to :class:`~threedecks.state.StateStore`, so the same command
resumes after any interruption. Incarnation links (``Previously`` / ``Becomes``)
are the only links ever followed.
"""

from __future__ import annotations

import hashlib
import logging
import sqlite3
from pathlib import Path

import scrapy
from parsel import Selector
from scrapy import signals
from scrapy.exceptions import IgnoreRequest
from scrapy.spidermiddlewares.httperror import HttpError
from scrapy.utils.defer import deferred_from_coro

from threedecks import PARSER_VERSION
from threedecks.items import extract_id
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship
from threedecks.state import StateStore, utc_iso, utcnow
from threedecks.ua import require_contact

logger = logging.getLogger(__name__)


class TDSpider(scrapy.Spider):
    default_max_depth = 1
    max_attempts = 3

    def __init__(self, base_url=None, data_dir=None, max_depth=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._base_url = base_url
        self._data_dir = data_dir
        self._max_depth = max_depth
        self._store: StateStore | None = None
        self._run_id: int | None = None
        self._requested: dict[int, int] = {}  # td_id -> shallowest depth requested this run
        self._network_streak: list[int] = []  # ids that got no response, in a row
        self._network_down = False
        self._incomplete_streak: list[int] = []  # distinct pages that failed completeness, in a row

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
        # Rule 2: refuse before any request (robots.txt included) goes out anonymously.
        require_contact(crawler.settings.get("USER_AGENT", ""))
        spider = super().from_crawler(crawler, *args, **kwargs)
        crawler.signals.connect(spider.on_opened, signal=signals.spider_opened)
        return spider

    def on_opened(self) -> None:
        self._run_id = self.store.start_run(self.name)

    async def start(self):
        """Scrapy 2.13+ entry point; keep the sync ``start_requests`` testable."""
        for request in self.start_requests():
            yield request

    # -- configuration -----------------------------------------------------
    @property
    def base_url(self) -> str:
        if self._base_url:
            return self._base_url.rstrip("/")
        return self.settings.get("THREEDECKS_BASE_URL", "https://threedecks.org").rstrip("/")

    @property
    def data_dir(self) -> Path:
        if self._data_dir:
            return Path(self._data_dir)
        return Path(self.settings["DATA_DIR"])

    @property
    def max_depth(self) -> int:
        if self._max_depth is not None:
            return int(self._max_depth)
        return int(self.settings.getint("THREEDECKS_MAX_DEPTH", self.default_max_depth))

    @property
    def network_failure_limit(self) -> int:
        try:
            return self.settings.getint("THREEDECKS_NETWORK_FAILURES", 3)
        except AttributeError:  # no crawler (offline tests)
            return 3

    @property
    def incomplete_limit(self) -> int:
        try:
            return self.settings.getint("THREEDECKS_INCOMPLETE_LIMIT", 3)
        except AttributeError:  # no crawler (offline tests)
            return 3

    @property
    def store(self) -> StateStore:
        if self._store is None:
            self._store = StateStore(self.data_dir / "state.sqlite")
        return self._store

    def closed(self, reason) -> None:
        if self._store is not None:
            if self._run_id is not None:
                pages = 0
                stats = getattr(self.crawler, "stats", None)
                if stats is not None:  # pages fetched from the site, not from the cache
                    pages = (stats.get_value("response_received_count", 0) or 0) - (
                        stats.get_value("httpcache/hit", 0) or 0
                    )
                try:
                    self._store.finish_run(
                        self._run_id, close_reason=reason, pages_fetched=int(pages)
                    )
                except Exception:  # never let logging the run hide the close
                    logger.exception("could not finish run record")
            self._store.close()
            self._store = None

    # -- request helpers ---------------------------------------------------
    def ship_url(self, td_id: int) -> str:
        return f"{self.base_url}/index.php?display_type=show_ship&id={int(td_id)}"

    def ship_request(self, td_id: int, *, depth: int = 0, discovered_by: str | None = None):
        return scrapy.Request(
            self.ship_url(td_id),
            callback=self.parse_ship_page,
            errback=self.on_ship_error,
            meta={"depth": depth, "discovered_by": discovered_by, "td_id": int(td_id)},
            dont_filter=True,
        )

    def ship_requests(self, td_ids, *, depth: int, discovered_by: str | None):
        """Requests for ids not yet requested in this run, at this depth or shallower.

        An id can be on a list and also be another ship's incarnation; it is
        fetched once per run, at its shallowest depth, so its own links are still
        followed. (Every later sighting would only replay the cache.)
        """
        for td_id in td_ids:
            td_id = int(td_id)
            if self._requested.get(td_id, depth + 1) <= depth:
                continue
            self._requested[td_id] = depth
            yield self.ship_request(td_id, depth=depth, discovered_by=discovered_by)

    def on_ship_error(self, failure):
        """Record a fetch that failed after Scrapy's retries (Plan 4.3, step 7).

        The row becomes ``error`` with one more attempt, so restarts retry it up
        to ``max_attempts`` and then leave it for manual review.
        """
        if failure.check(HttpError):  # before IgnoreRequest: HttpError subclasses it
            http_status = failure.value.response.status
        elif failure.check(IgnoreRequest):  # blocked, or robots.txt: leave the state intact
            return
        else:
            http_status = None
        request = failure.request
        td_id = request.meta.get("td_id") or extract_id(request.url)
        if td_id is None:
            return
        logger.warning("fetch failed for id %s: %s", td_id, failure.getErrorMessage())
        self._inc_stat("threedecks/fetch_error")
        self.store.mark_status(
            int(td_id),
            "error",
            http_status=http_status,
            error=failure.getErrorMessage()[:500],
            increment_attempts=True,
        )
        if http_status is None:  # no response at all: DNS, refused, timed out
            self._network_failure(int(td_id))

    def _network_failure(self, td_id: int) -> None:
        """A run of fetches with no response means the network or the site is
        down, not that these pages are bad. Give their attempts back and close
        with 'network_down', so an outage cannot use up every page's retries."""
        self._network_streak.append(td_id)
        if self._network_down:  # the page that was in flight when we gave up
            self.store.release_attempts([td_id])
            return
        if len(self._network_streak) < self.network_failure_limit:
            return
        self._network_down = True
        self.store.release_attempts(self._network_streak)
        logger.error(
            "%d fetches in a row got no response; closing with reason 'network_down' "
            "(their attempts are not counted)",
            len(self._network_streak),
        )
        self._close("network_down")

    def _close(self, reason: str) -> None:
        engine = getattr(getattr(self, "crawler", None), "engine", None)
        if engine is not None:  # no engine (offline tests)
            deferred_from_coro(engine.close_spider_async(reason=reason))

    def stream_pending(self):
        """Lazily request frontier rows that are not yet done or not found."""
        yield from self.ship_requests(
            self.store.pending_ids(max_attempts=self.max_attempts), depth=0, discovered_by="resume"
        )

    # -- default ship callback --------------------------------------------
    def parse_ship_page(self, response):
        self._network_streak.clear()  # a response arrived, so the network is up
        selector = Selector(text=response.text)
        td_id = extract_id(response.url) or response.meta.get("td_id")
        if td_id is None:
            return
        td_id = int(td_id)

        if is_not_found_page(selector):
            self._inc_stat("threedecks/not_found")
            self.store.mark_status(td_id, "not_found", http_status=response.status)
            return
        if not is_ship_page(selector):
            yield from self._record_incomplete(response, td_id)
            return
        self._incomplete_streak.clear()  # a complete, understood page

        # A page replayed from the cache keeps the time it was really fetched.
        cached_at = response.meta.get("cache_timestamp")
        try:
            record = parse_ship(
                selector,
                response.url,
                fetched_at=utc_iso(cached_at) if cached_at else utcnow(),
                content_sha256=hashlib.sha256(response.body).hexdigest(),
                parser_version=PARSER_VERSION,
            )
        except Exception as exc:  # the crawl moves on; fix the parser, then reparse.py
            logger.exception("parser failed for id %s; marking parse_error", td_id)
            self._inc_stat("threedecks/parse_error")
            self.store.mark_status(
                td_id, "parse_error", http_status=response.status, error=repr(exc)[:500]
            )
            return
        if record.td_id is None:
            record.td_id = td_id
        self._count_unknowns(record)
        yield record

        depth = int(response.meta.get("depth", 0))
        if depth < self.max_depth:
            others = sorted(set(record.previous_td_ids) | set(record.next_td_ids))
            self.store.seed(others, discovered_by="incarnation", depth=depth + 1)
            yield from self.ship_requests(others, depth=depth + 1, discovered_by="incarnation")

    def _count_unknowns(self, record) -> None:
        """Surface new labels and sections in the crawl stats (Plan 4, lossless capture)."""
        for label in record.unknown_labels:
            self._inc_stat(f"threedecks/unknown_label/{label}")
        for section in record.unknown_sections:
            self._inc_stat(f"threedecks/unknown_section/{section}")

    def _inc_stat(self, key: str) -> None:
        stats = getattr(getattr(self, "crawler", None), "stats", None)
        if stats is not None:  # no crawler (offline tests)
            stats.inc_value(key)

    # -- completeness (Plan 4.3, step 6) ----------------------------------
    def _record_incomplete(self, response, td_id: int):
        retries = response.meta.get("completeness_retries", 0)
        limit = self.incomplete_limit
        if retries == 0 and limit > 0:
            # Only first-attempt incompletes count: a single broken page must not
            # stop the crawl, but distinct pages in a row mean systemic trouble.
            self._incomplete_streak.append(td_id)
            if len(self._incomplete_streak) >= limit:
                logger.error(
                    "%d ship pages in a row failed the completeness check; closing with "
                    "reason 'incomplete_streak'. The site may be serving truncated pages "
                    "or the markup changed; run scripts/smoke.py and investigate.",
                    len(self._incomplete_streak),
                )
                self.store.release_attempts(
                    self._incomplete_streak,
                    reason="incomplete page streak; attempt not counted",
                )
                self._close("incomplete_streak")
                return  # no in-run retry: this needs human eyes, not another fetch
        logger.warning(
            "incomplete ship page for id %s at %s; marking error and dropping cache",
            td_id,
            response.url,
        )
        self._inc_stat("threedecks/incomplete_page")
        self.store.mark_status(
            td_id,
            "error",
            http_status=response.status,
            error="incomplete ship page",
            increment_attempts=True,
        )
        self.drop_cache_entry(response.request)
        # A truncated cache entry is refetched once in the same run, now that the
        # bad entry is gone; a genuinely broken page then stays an error.
        if retries < 1:
            retry = self.ship_request(
                td_id,
                depth=int(response.meta.get("depth", 0)),
                discovered_by=response.meta.get("discovered_by"),
            )
            retry.meta["completeness_retries"] = retries + 1
            yield retry

    def drop_cache_entry(self, request) -> None:
        """Delete a cached response so the page is refetched on the next run."""
        try:
            fingerprint = self.crawler.request_fingerprinter.fingerprint(request).hex()
        except AttributeError:  # no crawler (offline tests)
            return
        db_path = self.data_dir / "httpcache.sqlite"
        if not db_path.exists():
            return
        conn = sqlite3.connect(str(db_path))
        try:
            with conn:
                conn.execute("DELETE FROM responses WHERE fingerprint = ?", (fingerprint,))
        finally:
            conn.close()

    def _endpoint(self, display_type: str) -> str:
        return f"{self.base_url}/index.php?display_type={display_type}"
