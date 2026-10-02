"""Tier A: the captures list, and the ships it names (Plan 5).

One POST to the captures form; the captured and captor ships are then followed
to depth 1. This delivers the Spanish-losses core without the full catalogue.
"""

from __future__ import annotations

import scrapy
from parsel import Selector

from threedecks.parsing.captures import parse_captures
from threedecks.spiders.base import TDSpider


class CapturesSpider(TDSpider):
    name = "captures"
    default_max_depth = 1

    def __init__(self, from_nation=7, by_nation=1, war="", **kwargs):
        super().__init__(**kwargs)
        self.from_nation = int(from_nation)
        self.by_nation = int(by_nation)
        self.war = war or None

    @property
    def query(self) -> dict:
        return {
            "from_nation_id": self.from_nation,
            "by_nation_id": self.by_nation,
            "war_id": int(self.war) if self.war else None,
        }

    def start_requests(self):
        yield scrapy.FormRequest(
            self._endpoint("select_capture"),
            formdata={
                "select_from_nation": str(self.from_nation),
                "select_by_nation": str(self.by_nation),
                "select_war": self.war or "",
                "select_captures": "Change Filter",
            },
            callback=self.parse_captures,
            dont_filter=True,
        )

    def parse_captures(self, response):
        ship_ids: list[int] = []
        for row in parse_captures(Selector(text=response.text), self.query):
            yield row
            if row.captured_td_id is not None:
                ship_ids.append(row.captured_td_id)
            ship_ids.extend(row.captor_td_ids)

        unique = sorted(set(ship_ids))
        self.store.seed(unique, discovered_by=self.name, depth=1)
        for td_id in unique:
            yield self.ship_request(td_id, depth=1, discovered_by=self.name)
