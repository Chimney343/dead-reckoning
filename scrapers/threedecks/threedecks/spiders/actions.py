"""The ``actions`` crawler (Three Decks actions plan 5, 7).

It requests only two page types: the action index (a POST to ``select_action``)
and action pages (``show_battle``). Participant ships, places, wars and the
previous/next actions are stored as ids only, and the previous/next actions are
not followed, because the index lists every action.
"""

from __future__ import annotations

import logging

import scrapy
from parsel import Selector

from threedecks import kinds_actions  # noqa: F401  (registers the ACTION kind)
from threedecks.forms import action_index_form
from threedecks.parsing.actions import is_action_index_page, parse_action_index
from threedecks.spiders.base import TDSpider

logger = logging.getLogger(__name__)


class ActionsSpider(TDSpider):
    name = "actions"
    default_max_depth = 0

    def start_requests(self):
        targeted = self._targeted_action_ids()
        if targeted:
            # A smoke run names exact battles so the result is deterministic and
            # rich; the index (and its 1000+ discovered pages) is left untouched.
            self.store.seed_pages("action", targeted, discovered_by="targeted")
            yield from self.entity_requests(
                "action", [int(key) for key in targeted], discovered_by="targeted"
            )
            return
        # Seed from stored ship history first: it costs no requests.
        self.store.seed_pages(
            "action",
            [str(i) for i in self.store.history_battle_ids()],
            discovered_by="ship_history",
        )
        self.store.seed_pages("action_index", ["1"], discovered_by="start")
        # The index goes first (priority 10), then the pending actions in id order.
        for key in self.store.pending_pages("action_index", self.max_attempts):
            yield self.index_request(int(key))
        yield from self.stream_pending_pages("action")

    def _targeted_action_ids(self) -> list[str]:
        """Action ids named by ``THREEDECKS_ACTION_IDS``; empty means crawl normally."""
        try:
            values = self.settings.getlist("THREEDECKS_ACTION_IDS")
        except AttributeError:  # no crawler (offline tests)
            return []
        # Non-numeric entries are ignored so a typo cannot abort the crawl.
        return [str(value).strip() for value in values if str(value).strip().isdigit()]

    def index_request(self, page: int):
        return scrapy.FormRequest(
            f"{self.base_url}/index.php?display_type=select_action",
            formdata=action_index_form(page),
            callback=self.parse_index,
            errback=self.on_entity_error,
            meta={"kind": "action_index", "key": str(page), "depth": 0,
                  "discovered_by": "action_index"},
            dont_filter=True,
            priority=10,
        )

    def parse_index(self, response):
        key = str(response.meta.get("key"))
        self._network_streak.clear()  # a response arrived, so the network is up
        selector = Selector(text=response.text)

        if not is_action_index_page(selector):
            yield from self._record_index_incomplete(response, key)
            return
        self._incomplete_streak.clear()

        try:
            page = parse_action_index(selector)
        except Exception as exc:  # the crawl moves on; fix the parser, then reparse.py
            logger.exception("parser failed for action index page %s; marking parse_error", key)
            self._inc_entity_stat("action_index", "parse_error")
            self.store.mark_page_status(
                "action_index", key, "parse_error", http_status=response.status,
                error=repr(exc)[:500],
            )
            return

        rows = page.rows
        self.store.save_action_index_page(key, rows)
        self._inc_stat("threedecks/action_index/rows", len(rows))
        self._inc_stat(
            "threedecks/action_index/row_without_id",
            sum(1 for row in rows if row.battle_id is None),
        )

        if page.pages and page.pages > 1:
            new_pages = self.store.seed_pages(
                "action_index",
                [str(number) for number in range(2, page.pages + 1)],
                discovered_by="action_index",
            )
            for number in new_pages:
                yield self.index_request(int(number))

        ids = [str(row.battle_id) for row in rows if row.battle_id is not None]
        new_ids = self.store.seed_pages("action", ids, discovered_by="action_index")
        yield from self.entity_requests("action", [int(i) for i in new_ids])

    def _record_index_incomplete(self, response, key: str):
        retries = response.meta.get("completeness_retries", 0)
        limit = self.incomplete_limit
        if retries == 0 and limit > 0:
            self._incomplete_streak.append(("action_index", key))
            if len(self._incomplete_streak) >= limit:
                logger.error(
                    "%d pages in a row failed the completeness check; closing with "
                    "reason 'incomplete_streak'.",
                    len(self._incomplete_streak),
                )
                self._release_streak("action_index", self._incomplete_streak)
                self._close("incomplete_streak")
                return
        logger.warning("incomplete action index page at %s; marking error", response.url)
        self._inc_entity_stat("action_index", "incomplete_page")
        self.store.mark_page_status(
            "action_index", key, "error", http_status=response.status,
            error="incomplete action index page", increment_attempts=True,
        )
        self.drop_cache_entry(response.request)
        if retries < 1:
            retry = self.index_request(int(key))
            retry.meta["completeness_retries"] = retries + 1
            yield retry
