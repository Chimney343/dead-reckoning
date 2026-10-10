"""Parser for the Captures list (Plan 3.1, 4.1).

Columns: date, captured ship (``a.shiplink``), then captor ship(s) followed by
optional free text and ``. Place``. Rows may lack a captor link (free text only)
or even a captured-ship link; both are kept, with the parsed id left ``None``.
"""

from __future__ import annotations

import re

from parsel import Selector

from threedecks.items import CaptureRow, extract_id
from threedecks.parsing.dates import parse_td_date

_ROWS = ".//table[@id='capture_list']//tr"
_VISIBLE = ".//text()[not(ancestor::span[contains(@class,'tooltiptext')])]"
_FROM_NATIONS = "//select[@id='select_from_nation']/option/@value"


def _norm(texts: list[str]) -> str:
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def parse_capture_nations(selector: Selector) -> list[int]:
    """The "Taken from" nation ids in the captures form, in form order.

    The placeholder option (value 0, "Please Select...") is dropped: the form
    requires at least one nation, so it is the list of queries that together
    return every capture. Values keep their first-seen order and are unique.
    """
    nations: list[int] = []
    for value in selector.xpath(_FROM_NATIONS).getall():
        try:
            nation_id = int(value)
        except (TypeError, ValueError):
            continue
        if nation_id > 0 and nation_id not in nations:
            nations.append(nation_id)
    return nations


def _visible_text(cell) -> str:
    return _norm(cell.xpath(_VISIBLE).getall())


def _first_ship_link(cell) -> tuple[int | None, str]:
    links = cell.xpath(".//a[contains(@href,'show_ship')]")
    if not links:
        return None, ""
    return extract_id(links[0].xpath("./@href").get()), _norm(
        links[0].xpath(".//text()").getall()
    )


def _place_from_text(text: str) -> str | None:
    match = re.search(r"\.\s*(.+)$", text)
    if not match:
        return None
    place = match.group(1).strip()
    return place or None


def parse_captures(selector: Selector, query: dict) -> list[CaptureRow]:
    """Parse ``table#capture_list`` into rows, given the query that produced it."""
    rows: list[CaptureRow] = []
    for tr in selector.xpath(_ROWS):
        if tr.xpath("./th"):
            continue
        cells = tr.xpath("./td")
        if not cells:
            continue

        date_span = cells[0].xpath(".//span[contains(@class,'date_field')]")
        if date_span:
            raw = _norm(date_span[0].xpath(".//text()").getall())
            tooltip = date_span[0].xpath("./@title").get()
        else:
            raw, tooltip = _visible_text(cells[0]), None
        date = parse_td_date(raw, tooltip)

        captured_id: int | None = None
        captured_label = ""
        if len(cells) > 1:
            captured_id, captured_label = _first_ship_link(cells[1])
            if not captured_label:
                captured_label = _visible_text(cells[1])

        captor_ids: list[int] = []
        captor_text = ""
        place_text: str | None = None
        if len(cells) > 2:
            for href in cells[2].xpath(".//a[contains(@href,'show_ship')]/@href").getall():
                captor_id = extract_id(href)
                if captor_id is not None:
                    captor_ids.append(captor_id)
            captor_text = _visible_text(cells[2])
            place_text = _place_from_text(captor_text)

        rows.append(
            CaptureRow(
                captured_td_id=captured_id,
                captured_label=captured_label,
                date=date,
                captor_td_ids=captor_ids,
                captor_text=captor_text,
                place_text=place_text,
                from_nation_id=query.get("from_nation_id"),
                by_nation_id=query.get("by_nation_id"),
                war_id=query.get("war_id"),
            )
        )
    return rows
