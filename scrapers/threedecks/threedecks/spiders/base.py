"""Shared spider behaviour (Plan 4, 5; Task S4).

A spider only builds requests and calls the pure parsers. Progress is read from
and written to :class:`~threedecks.state.StateStore`, so the same command
resumes after any interruption. Incarnation links (``Previously`` / ``Becomes``)
are the only links ever followed, and only for ship pages.

The entity path is kind-agnostic: :meth:`TDSpider.parse_entity_page` drives any
registered :class:`~threedecks.pages.PageKind`. Ship requests and callbacks stay
as thin wrappers, so the ship spiders and their tests are unchanged.
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

from threedecks.items import extract_id
from threedecks.pages import KINDS
from threedecks.parsing.ship_page import parse_ship
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
        # (kind, id) -> shallowest depth requested this run.
        self._requested: dict[tuple[str, int], int] = {}
        # Streak entries: bare ints for ships, (kind, key) pairs for other kinds.
        self._network_streak: list = []  # ids that got no response, in a row
        self._network_down = False
        self._incomplete_streak: list = []  # distinct pages that failed completeness, in a row

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
    def entity_url(self, kind: str, id) -> str:
        return f"{self.base_url}/index.php?display_type={KINDS[kind].display_type}&id={int(id)}"

    def ship_url(self, td_id: int) -> str:
        return self.entity_url("ship", td_id)

    def entity_request(self, kind: str, id, *, depth: int = 0,
                       discovered_by: str | None = None, priority: int = 0):
        key = str(int(id))
        meta = {"depth": depth, "discovered_by": discovered_by, "kind": kind, "key": key}
        if kind == "ship":
            meta["td_id"] = int(id)
        return scrapy.Request(
            self.entity_url(kind, id),
            callback=self.parse_entity_page,
            errback=self.on_entity_error,
            meta=meta,
            dont_filter=True,
            priority=priority,
        )

    def entity_requests(self, kind: str, ids, *, depth: int = 0,
                        discovered_by: str | None = None, priority: int = 0):
        """Requests for ids not yet requested in this run, at this depth or shallower.

        An id can be discovered more than once; it is fetched once per run, at
        its shallowest depth, so its own links are still followed.
        """
        for id in ids:
            id = int(id)
            marker = (kind, id)
            if self._requested.get(marker, depth + 1) <= depth:
                continue
            self._requested[marker] = depth
            yield self.entity_request(
                kind, id, depth=depth, discovered_by=discovered_by, priority=priority
            )

    def ship_request(self, td_id: int, *, depth: int = 0, discovered_by: str | None = None):
        return scrapy.Request(
            self.ship_url(td_id),
            callback=self.parse_ship_page,
            errback=self.on_ship_error,
            meta={"depth": depth, "discovered_by": discovered_by, "td_id": int(td_id),
                  "kind": "ship", "key": str(int(td_id))},
            dont_filter=True,
        )

    def ship_requests(self, td_ids, *, depth: int, discovered_by: str | None):
        yield from self.entity_requests("ship", td_ids, depth=depth, discovered_by=discovered_by)

    # -- errors ------------------------------------------------------------
    def on_entity_error(self, failure):
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
        kind = request.meta.get("kind", "ship")
        key = request.meta.get("key")
        if key is None:
            found = request.meta.get("td_id") or extract_id(request.url)
            if found is None:
                return
            kind, key = "ship", str(int(found))
        logger.warning("fetch failed for %s %s: %s", kind, key, failure.getErrorMessage())
        self._inc_entity_stat(kind, "fetch_error")
        self._mark(
            kind,
            key,
            "error",
            http_status=http_status,
            error=failure.getErrorMessage()[:500],
            increment_attempts=True,
        )
        if http_status is None:  # no response at all: DNS, refused, timed out
            self._network_failure(kind, key)

    def on_ship_error(self, failure):
        return self.on_entity_error(failure)

    def _network_failure(self, kind: str, key) -> None:
        """A run of fetches with no response means the network or the site is
        down, not that these pages are bad. Give their attempts back and close
        with 'network_down', so an outage cannot use up every page's retries."""
        self._network_streak.append(self._streak_key(kind, key))
        if self._network_down:  # the page that was in flight when we gave up
            self._release_streak(kind, self._network_streak)
            return
        if len(self._network_streak) < self.network_failure_limit:
            return
        self._network_down = True
        self._release_streak(kind, self._network_streak)
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

    # -- frontier helpers (ship vs page namespaces) ------------------------
    @staticmethod
    def _streak_key(kind: str, key):
        return int(key) if kind == "ship" else (kind, str(key))

    def _release_streak(self, kind: str, streak) -> None:
        reason = "network down; attempt not counted"
        if kind == "ship":
            self.store.release_attempts([int(entry) for entry in streak], reason=reason)
        else:
            keys = [entry[1] for entry in streak if isinstance(entry, tuple) and entry[0] == kind]
            self.store.release_page_attempts(kind, keys, reason=reason)

    def _mark(self, kind: str, key, status: str, **kwargs) -> None:
        if kind == "ship":
            self.store.mark_status(int(key), status, **kwargs)
        else:
            self.store.mark_page_status(kind, key, status, **kwargs)

    def stream_pending(self):
        """Lazily request ship frontier rows that are not yet done or not found."""
        yield from self.ship_requests(
            self.store.pending_ids(max_attempts=self.max_attempts), depth=0, discovered_by="resume"
        )

    def stream_pending_pages(self, kind: str):
        """Lazily request page-frontier rows of ``kind`` that still need a fetch."""
        if kind == "ship":
            yield from self.stream_pending()
            return
        yield from self.entity_requests(
            kind,
            self.store.pending_pages(kind, max_attempts=self.max_attempts),
            depth=0,
            discovered_by="resume",
        )

    # -- default entity callback ------------------------------------------
    def _entity_parse(self, kind: str, selector, response, *, fetched_at: str,
                      content_sha256: str):
        # ``parse_ship`` is looked up as a module global so a test can monkeypatch
        # it (the ship parser is not routed through the registry's bound callable).
        parser = parse_ship if kind == "ship" else KINDS[kind].parse
        return parser(
            selector,
            response.url,
            fetched_at=fetched_at,
            content_sha256=content_sha256,
            parser_version=KINDS[kind].parser_version,
        )

    def parse_entity_page(self, response):
        kind = response.meta.get("kind", "ship")
        key = response.meta.get("key")
        if key is None:
            found = response.meta.get("td_id") or extract_id(response.url)
            if found is None:
                return
            kind, key = "ship", str(int(found))
        key = str(key)
        kind_obj = KINDS[kind]
        self._network_streak.clear()  # a response arrived, so the network is up
        selector = Selector(text=response.text)

        if kind_obj.is_not_found(selector):
            self._inc_entity_stat(kind, "not_found")
            self._mark(kind, key, "not_found", http_status=response.status)
            return
        if not kind_obj.is_page(selector):
            yield from self._record_entity_incomplete(response, kind, key)
            return
        self._incomplete_streak.clear()  # a complete, understood page

        # A page replayed from the cache keeps the time it was really fetched.
        cached_at = response.meta.get("cache_timestamp")
        try:
            record = self._entity_parse(
                kind,
                selector,
                response,
                fetched_at=utc_iso(cached_at) if cached_at else utcnow(),
                content_sha256=hashlib.sha256(response.body).hexdigest(),
            )
        except Exception as exc:  # the crawl moves on; fix the parser, then reparse.py
            logger.exception("parser failed for %s %s; marking parse_error", kind, key)
            self._inc_entity_stat(kind, "parse_error")
            self._mark(kind, key, "parse_error", http_status=response.status,
                       error=repr(exc)[:500])
            return

        if kind == "ship":
            yield from self._finish_ship(record, response, key)
        else:
            yield from self._finish_entity(record, kind)

    def _finish_ship(self, record, response, key: str):
        td_id = int(key)
        if record.td_id is None:
            record.td_id = td_id
        self._count_unknowns(record, "ship")
        yield record

        depth = int(response.meta.get("depth", 0))
        if depth < self.max_depth:
            others = sorted(set(record.previous_td_ids) | set(record.next_td_ids))
            self.store.seed(others, discovered_by="incarnation", depth=depth + 1)
            yield from self.ship_requests(others, depth=depth + 1, discovered_by="incarnation")

    def _finish_entity(self, record, kind: str):
        self._count_unknowns(record, kind)
        yield record

    def parse_ship_page(self, response):
        response.meta.setdefault("kind", "ship")
        if response.meta.get("key") is None:
            found = response.meta.get("td_id") or extract_id(response.url)
            if found is not None:
                response.meta["key"] = str(int(found))
        yield from self.parse_entity_page(response)

    def _count_unknowns(self, record, kind: str = "ship") -> None:
        """Surface new labels and sections in the crawl stats (Plan 4, lossless capture)."""
        for label in getattr(record, "unknown_labels", None) or []:
            self._inc_stat(self._stat_key(kind, f"unknown_label/{label}"))
        for section in getattr(record, "unknown_sections", None) or []:
            self._inc_stat(self._stat_key(kind, f"unknown_section/{section}"))

    @staticmethod
    def _stat_key(kind: str, name: str) -> str:
        return f"threedecks/{name}" if kind == "ship" else f"threedecks/{kind}/{name}"

    def _inc_entity_stat(self, kind: str, name: str) -> None:
        self._inc_stat(self._stat_key(kind, name))

    def _inc_stat(self, key: str, count: int = 1) -> None:
        stats = getattr(getattr(self, "crawler", None), "stats", None)
        if stats is not None:  # no crawler (offline tests)
            stats.inc_value(key, count)

    # -- completeness (Plan 4.3, step 6) ----------------------------------
    def _record_entity_incomplete(self, response, kind: str, key: str):
        retries = response.meta.get("completeness_retries", 0)
        limit = self.incomplete_limit
        if retries == 0 and limit > 0:
            # Only first-attempt incompletes count: a single broken page must not
            # stop the crawl, but distinct pages in a row mean systemic trouble.
            self._incomplete_streak.append(self._streak_key(kind, key))
            if len(self._incomplete_streak) >= limit:
                logger.error(
                    "%d pages in a row failed the completeness check; closing with "
                    "reason 'incomplete_streak'. The site may be serving truncated pages "
                    "or the markup changed; run scripts/smoke.py and investigate.",
                    len(self._incomplete_streak),
                )
                self._release_streak(kind, self._incomplete_streak)
                self._close("incomplete_streak")
                return  # no in-run retry: this needs human eyes, not another fetch
        logger.warning(
            "incomplete %s page at %s; marking error and dropping cache",
            kind,
            response.url,
        )
        self._inc_entity_stat(kind, "incomplete_page")
        self._mark(
            kind,
            key,
            "error",
            http_status=response.status,
            error="incomplete page",
            increment_attempts=True,
        )
        self.drop_cache_entry(response.request)
        # A truncated cache entry is refetched once in the same run, now that the
        # bad entry is gone; a genuinely broken page then stays an error.
        if retries < 1:
            retry = self._entity_retry(kind, key, response)
            retry.meta["completeness_retries"] = retries + 1
            yield retry

    def _entity_retry(self, kind: str, key: str, response):
        depth = int(response.meta.get("depth", 0))
        discovered_by = response.meta.get("discovered_by")
        if kind == "ship":
            return self.ship_request(int(key), depth=depth, discovered_by=discovered_by)
        return self.entity_request(kind, int(key), depth=depth, discovered_by=discovered_by)

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
