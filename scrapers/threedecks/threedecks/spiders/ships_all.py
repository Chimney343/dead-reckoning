"""Tier C: every ship id (Plan 5).

Seeds the 25,300 ids in ``ships.xml`` and every other id up to the highest id
known (the sitemap's or the frontier's, whichever is higher), then scans upward
from there until 200 consecutive not-found responses. The upward
stop position lives in the frontier (the trailing ``not_found`` rows), so a
resumed run continues the scan rather than restarting it.
"""

from __future__ import annotations

import scrapy
from parsel import Selector

from threedecks.items import extract_id
from threedecks.spiders.base import TDSpider


class ShipsAllSpider(TDSpider):
    name = "ships_all"
    default_max_depth = 0
    default_upward_limit = 200

    @property
    def upward_limit(self) -> int:
        try:
            return int(self.settings.getint("THREEDECKS_UPWARD_LIMIT", self.default_upward_limit))
        except AttributeError:  # no crawler (offline tests)
            return self.default_upward_limit

    def start_requests(self):
        yield scrapy.Request(
            f"{self.base_url}/ships.xml",
            callback=self.parse_sitemap,
            dont_filter=True,
        )

    def parse_sitemap(self, response):
        selector = Selector(text=response.text, type="xml")
        ids = sorted(
            {
                td_id
                for td_id in (
                    extract_id(loc)
                    for loc in selector.xpath("//*[local-name()='loc']/text()").getall()
                )
                if td_id is not None
            }
        )
        if ids:
            self.store.seed(ids, discovered_by="sitemap")
        # Fill every id up to the highest one known, not just the sitemap's: the
        # sitemap is stale (max 28,756) while Tier A finds ids above 34,000, and
        # the upward scan starts above the frontier's maximum.
        top = max(max(ids, default=0), self.store.max_td_id() or 0)
        known = set(ids)
        gaps = [i for i in range(1, top + 1) if i not in known]
        self.store.seed(gaps, discovered_by="gap")  # INSERT OR IGNORE: known rows stay
        yield from self.stream_pending()
        yield self.upward_request()

    def upward_request(self):
        next_id = (self.store.max_td_id() or 0) + 1
        self.store.seed([next_id], discovered_by="upward")
        return self.ship_request(next_id, depth=0, discovered_by="upward")

    def parse_ship_page(self, response):
        yield from super().parse_ship_page(response)
        if response.meta.get("discovered_by") != "upward":
            return
        td_id = extract_id(response.url)
        if td_id is None:
            return
        if self.store.status(td_id) == "not_found":
            if self.store.trailing_not_found() >= self.upward_limit:
                return
        yield self.upward_request()
