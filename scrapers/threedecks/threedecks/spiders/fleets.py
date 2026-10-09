"""The ``fleets`` crawler (Three Decks fleets plan 4.3, 7).

It requests only two page types: the fleet-list index (GET ``show_fleetlist``)
and fleet pages (``show_fleet``). Fleet ships, commanders, places and the actions
linked from events are stored as ids only; event links are never followed. The
fleet index is one GET page (no pagination).
"""

from __future__ import annotations

import logging

import scrapy
from parsel import Selector

from threedecks import kinds_fleets  # noqa: F401  (registers the FLEET kind)
from threedecks.parsing.fleets import is_fleetlist_index_page, parse_fleet_index
from threedecks.spiders.base import TDSpider

logger = logging.getLogger(__name__)


class FleetsSpider(TDSpider):
    name = "fleets"
    default_max_depth = 0

    def start_requests(self):
        # Seed from stored ship records first: it costs no requests.
        self.store.seed_pages(
            "fleet",
            [str(i) for i in self.store.ship_fleet_ids()],
            discovered_by="ship_fleets",
        )
        self.store.seed_pages("fleet_index", ["1"], discovered_by="start")
        # The index goes first (priority 10), then the pending fleets in id order.
        if (
            self.store.page_status("fleet_index", "1") in ("pending", "error")
            and self.store.page_attempts("fleet_index", "1") < self.max_attempts
        ):
            yield self.index_request()
        yield from self.stream_pending_pages("fleet")

    def index_request(self):
        return scrapy.Request(
            f"{self.base_url}/index.php?display_type=show_fleetlist",
            callback=self.parse_index,
            errback=self.on_entity_error,
            meta={"kind": "fleet_index", "key": "1", "depth": 0,
                  "discovered_by": "fleet_index"},
            dont_filter=True,
            priority=10,
        )

    def parse_index(self, response):
        key = str(response.meta.get("key"))
        self._network_streak.clear()  # a response arrived, so the network is up
        selector = Selector(text=response.text)

        if not is_fleetlist_index_page(selector):
            yield from self._record_index_incomplete(response, key)
            return
        self._incomplete_streak.clear()

        try:
            rows = parse_fleet_index(selector)
        except Exception as exc:  # the crawl moves on; fix the parser, then reparse.py
            logger.exception("parser failed for fleet index page %s; marking parse_error", key)
            self._inc_entity_stat("fleet_index", "parse_error")
            self.store.mark_page_status(
                "fleet_index", key, "parse_error", http_status=response.status,
                error=repr(exc)[:500],
            )
            return

        self.store.save_fleet_index(rows)
        self._inc_stat("threedecks/fleet_index/rows", len(rows))
        self._inc_stat(
            "threedecks/fleet_index/row_without_id",
            sum(1 for row in rows if row.fleet_id is None),
        )

        ids = [str(row.fleet_id) for row in rows if row.fleet_id is not None]
        new_ids = self.store.seed_pages("fleet", ids, discovered_by="fleet_index")
        yield from self.entity_requests("fleet", [int(i) for i in new_ids])

    def _record_index_incomplete(self, response, key: str):
        retries = response.meta.get("completeness_retries", 0)
        limit = self.incomplete_limit
        if retries == 0 and limit > 0:
            self._incomplete_streak.append(("fleet_index", key))
            if len(self._incomplete_streak) >= limit:
                logger.error(
                    "%d pages in a row failed the completeness check; closing with "
                    "reason 'incomplete_streak'.",
                    len(self._incomplete_streak),
                )
                self._release_streak("fleet_index", self._incomplete_streak)
                self._close("incomplete_streak")
                return
        logger.warning("incomplete fleet index page at %s; marking error", response.url)
        self._inc_entity_stat("fleet_index", "incomplete_page")
        self.store.mark_page_status(
            "fleet_index", key, "error", http_status=response.status,
            error="incomplete fleet index page", increment_attempts=True,
        )
        self.drop_cache_entry(response.request)
        if retries < 1:
            retry = self.index_request()
            retry.meta["completeness_retries"] = retries + 1
            yield retry
