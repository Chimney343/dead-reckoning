"""Tier B (optional): ship search by nation, paginated (Plan 5).

Useful when the Spanish records are wanted before Tier C finishes; Tier C
fetches them anyway.
"""

from __future__ import annotations

import scrapy
from parsel import Selector

from threedecks.parsing.search import parse_search
from threedecks.spiders.base import TDSpider


class ShipsByNationSpider(TDSpider):
    name = "ships_by_nation"
    default_max_depth = 2

    def __init__(self, nation=7, origin=None, limit=50, **kwargs):
        super().__init__(**kwargs)
        self.nation = int(nation)
        self.origin = int(origin) if origin not in (None, "", "None") else None
        self.limit = int(limit)

    def start_requests(self):
        yield self.search_request(1)

    def search_request(self, page: int):
        formdata = {
            "show_shiplist": "1",
            "page": str(page),
            "limit": str(self.limit),
            "select_nation": str(self.nation),
        }
        if self.origin is not None:
            formdata["sel_origin"] = str(self.origin)
        return scrapy.FormRequest(
            self._endpoint("ships_search"),
            formdata=formdata,
            callback=self.parse_search,
            meta={"page": page},
            dont_filter=True,
        )

    def parse_search(self, response):
        result = parse_search(Selector(text=response.text))
        self.store.seed(result.ship_ids, discovered_by=self.name, depth=1)
        for td_id in result.ship_ids:
            yield self.ship_request(td_id, depth=1, discovered_by=self.name)
        if result.has_next:
            next_page = (result.page or response.meta.get("page", 1)) + 1
            yield self.search_request(next_page)
