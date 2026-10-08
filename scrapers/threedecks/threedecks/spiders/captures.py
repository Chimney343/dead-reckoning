"""Tier A: the captures list, and the ships it names (Plan 5).

One POST to the captures form (depth 0). The captured and captor ships it names
are fetched at depth 1, and their ``Previously`` / ``Becomes`` incarnations one
hop further, at depth 2, so a Spanish ship taken into British service yields
both records. This delivers the Spanish-losses core without the full catalogue.
"""

from __future__ import annotations

import scrapy
from parsel import Selector

from threedecks.parsing.captures import parse_captures
from threedecks.spiders.base import TDSpider


class CapturesSpider(TDSpider):
    name = "captures"
    default_max_depth = 2

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
        # The list is a snapshot: replace this query's rows rather than add to them.
        # A crash before they are re-saved is harmless; the next run replays the
        # cached POST.
        self.store.clear_captures(self.from_nation, self.by_nation, self.query["war_id"])
        ship_ids: list[int] = []
        for row in parse_captures(Selector(text=response.text), self.query):
            yield row
            if row.captured_td_id is not None:
                ship_ids.append(row.captured_td_id)
            ship_ids.extend(row.captor_td_ids)

        unique = sorted(set(ship_ids))
        self.store.seed(unique, discovered_by=self.name, depth=1)
        yield from self.ship_requests(unique, depth=1, discovered_by=self.name)
