"""Tier A: the captures list, for every captured-vessel nation (Plan 5).

The captures form cannot return the whole list in one query: with neither nation
selected it comes back empty, and the site requires at least one side of the
filter. So the spider reads the form once, takes every nation in its "Taken
from" select, and POSTs one query per nation, which returns that nation's
captured vessels with every captor. Together they are the full captures list.

The captured and captor ships each query names are fetched at depth 1, and their
``Previously`` / ``Becomes`` incarnations one hop further, at depth 2, so a ship
taken into foreign service yields both records.

Pass ``from_nation`` and (optionally) ``by_nation`` to run a single, restricted
query instead; the smoke test uses that for Spain -> Great Britain.
"""

from __future__ import annotations

import logging

import scrapy
from parsel import Selector

from threedecks.parsing.captures import parse_capture_nations, parse_captures
from threedecks.spiders.base import TDSpider

logger = logging.getLogger(__name__)


def _optional_int(value) -> int | None:
    if value in (None, "", "None"):
        return None
    return int(value)


class CapturesSpider(TDSpider):
    name = "captures"
    default_max_depth = 2

    def __init__(self, from_nation=None, by_nation=0, war="", **kwargs):
        super().__init__(**kwargs)
        # No from_nation means "every nation": the full crawl is the default.
        self.from_nation = _optional_int(from_nation)
        self.by_nation = _optional_int(by_nation) or 0
        self.war = war or None

    @property
    def query(self) -> dict:
        return {
            "from_nation_id": self.from_nation,
            "by_nation_id": self.by_nation,
            "war_id": int(self.war) if self.war else None,
        }

    def start_requests(self):
        if self.from_nation is not None:
            yield self.filter_request(self.from_nation, self.by_nation)
            return
        # Read the form to learn every "Taken from" nation, then query each.
        yield scrapy.Request(
            self._endpoint("select_capture"),
            callback=self.parse_nations,
            dont_filter=True,
        )

    def parse_nations(self, response):
        nations = parse_capture_nations(Selector(text=response.text))
        if not nations:
            logger.error("no nations in the captures form; the markup may have changed")
            return
        # The full crawl replaces every row, so drop the old (narrower) rows first.
        self.store.clear_all_captures()
        for nation_id in nations:
            yield self.filter_request(nation_id, self.by_nation)

    def filter_request(self, from_nation: int, by_nation: int):
        war_id = int(self.war) if self.war else None
        return scrapy.FormRequest(
            self._endpoint("select_capture"),
            formdata={
                "select_from_nation": str(from_nation),
                "select_by_nation": str(by_nation),
                "select_war": self.war or "",
                "select_captures": "Change Filter",
            },
            callback=self.parse_captures,
            meta={
                "query": {
                    "from_nation_id": from_nation,
                    "by_nation_id": by_nation,
                    "war_id": war_id,
                }
            },
            dont_filter=True,
        )

    def parse_captures(self, response):
        query = response.meta.get("query") or self.query
        # The list is a snapshot: replace this query's rows rather than add to them.
        # A crash before they are re-saved is harmless; the next run replays the
        # cached POST.
        self.store.clear_captures(
            query["from_nation_id"], query["by_nation_id"], query["war_id"]
        )
        ship_ids: list[int] = []
        for row in parse_captures(Selector(text=response.text), query):
            yield row
            if row.captured_td_id is not None:
                ship_ids.append(row.captured_td_id)
            ship_ids.extend(row.captor_td_ids)

        unique = sorted(set(ship_ids))
        self.store.seed(unique, discovered_by=self.name, depth=1)
        yield from self.ship_requests(unique, depth=1, discovered_by=self.name)
