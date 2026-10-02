"""Parser for the ship search results (Plan 3.1, 5 Tier B).

The results table is ``table#shiplists``; data rows carry
``class="shiplistdetailrow"``. A renamed vessel links both of its names, so only
the first ``show_ship`` link in the Name cell is the row's ship id.

Header text carries the totals: "Ship Search Results, 1863 Records Found
Showing Page 1 of 38".
"""

from __future__ import annotations

import re

from parsel import Selector

from threedecks.items import SearchPage, extract_id

_DATA_ROW = ".//table[@id='shiplists']//tr[contains(@class,'shiplistdetailrow')]"
_NAME_CELL = "./td[2]//a[contains(@href,'show_ship')]"
_TOTAL = re.compile(r"([\d,]+)\s+Records Found")
_PAGE = re.compile(r"Showing Page (\d+) of (\d+)")


def parse_search(selector: Selector) -> SearchPage:
    """Parse one results page into its ship ids, page position and totals."""
    ship_ids: list[int] = []
    for row in selector.xpath(_DATA_ROW):
        links = row.xpath(_NAME_CELL)
        if not links:
            continue
        td_id = extract_id(links[0].xpath("./@href").get())
        if td_id is not None:
            ship_ids.append(td_id)

    text = re.sub(r"\s+", " ", " ".join(selector.xpath("//text()").getall()))
    total_match = _TOTAL.search(text)
    page_match = _PAGE.search(text)
    total = int(total_match.group(1).replace(",", "")) if total_match else None
    page = int(page_match.group(1)) if page_match else None
    pages = int(page_match.group(2)) if page_match else None
    has_next = bool(page is not None and pages is not None and page < pages)

    return SearchPage(ship_ids=ship_ids, page=page, pages=pages, total=total, has_next=has_next)
