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

from threedecks import PARSER_VERSION
from threedecks.items import extract_id
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship
from threedecks.state import StateStore, utcnow

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

    @classmethod
    def from_crawler(cls, crawler, *args, **kwargs):
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
    def store(self) -> StateStore:
        if self._store is None:
            self._store = StateStore(self.data_dir / "state.sqlite")
        return self._store

    def closed(self, reason) -> None:
        if self._store is not None:
            if self._run_id is not None:
                pages = 0
                stats = getattr(self.crawler, "stats", None)
                if stats is not None:
                    pages = stats.get_value("item_scraped_count", 0) or 0
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
            meta={"depth": depth, "discovered_by": discovered_by, "td_id": int(td_id)},
            dont_filter=True,
        )

    def stream_pending(self):
        """Lazily request frontier rows that are not yet done or not found."""
        for td_id in self.store.pending_ids(max_attempts=self.max_attempts):
            yield self.ship_request(td_id, depth=0, discovered_by="resume")

    # -- default ship callback --------------------------------------------
    def parse_ship_page(self, response):
        selector = Selector(text=response.text)
        td_id = extract_id(response.url) or response.meta.get("td_id")
        if td_id is None:
            return
        td_id = int(td_id)

        if is_not_found_page(selector):
            self.store.mark_status(td_id, "not_found", http_status=response.status)
            return
        if not is_ship_page(selector):
            yield from self._record_incomplete(response, td_id)
            return

        record = parse_ship(
            selector,
            response.url,
            fetched_at=utcnow(),
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            parser_version=PARSER_VERSION,
        )
        if record.td_id is None:
            record.td_id = td_id
        yield record

        depth = int(response.meta.get("depth", 0))
        if depth < self.max_depth:
            for other in sorted(set(record.previous_td_ids) | set(record.next_td_ids)):
                self.store.seed([other], discovered_by="incarnation", depth=depth + 1)
                yield self.ship_request(
                    other, depth=depth + 1, discovered_by="incarnation"
                )

    # -- completeness (Plan 4.3, step 6) ----------------------------------
    def _record_incomplete(self, response, td_id: int):
        logger.warning(
            "incomplete ship page for id %s at %s; marking error and dropping cache",
            td_id,
            response.url,
        )
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
        if response.meta.get("completeness_retries", 0) < 1:
            retry = self.ship_request(
                td_id,
                depth=int(response.meta.get("depth", 0)),
                discovered_by=response.meta.get("discovered_by"),
            )
            retry.meta["completeness_retries"] = (
                response.meta.get("completeness_retries", 0) + 1
            )
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
