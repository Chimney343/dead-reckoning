"""Parsers for the action index and action pages (Three Decks actions plan 3).

Extraction is scoped to ``div#datacol`` so the sidebars and the comment table
(which are full of ``a.shiplink``) can never leak into a record. Visible text
never contains hover-card text; the card's lines stay in ``LinkRef.tooltip``.
"""

from __future__ import annotations

import re

from threedecks.items import (
    ActionDivision,
    ActionIndexPage,
    ActionIndexRow,
    ActionRecord,
    ActionSide,
    Participant,
    extract_id,
)
from threedecks.parsing import common
from threedecks.parsing.dates import parse_long_date, parse_td_date

ACTION_PARSER_VERSION = "1"

IGNORED_SECTIONS = {"Notes on Action", "Sources", "Recent comments to other pages"}

_POSITION = re.compile(
    r"position:\s*new google\.maps\.LatLng\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)"
)
_RECORDS_FOUND = re.compile(r"([\d,]+)\s+Records Found")
_SHOWING_PAGE = re.compile(r"Showing Page\s+(\d+)\s+of\s+(\d+)")


def _td_class(tr, name: str):
    cells = tr.xpath(
        f"./td[contains(concat(' ', normalize-space(@class), ' '), ' {name} ')]"
    )
    return cells[0] if cells else None


def is_action_page(sel) -> bool:
    """A completeness check: the info table, a title and the footer."""
    if not sel.xpath("//table[@id='table_action_info']") or not common.has_footer(sel):
        return False
    h1 = sel.xpath("//div[@id='datacol']//h1")
    return bool(h1) and bool(common.visible_text(h1[0]))


def is_action_not_found(sel) -> bool:
    """A missing action id answers with the "Find an action" page (after a 302)."""
    if is_action_page(sel):
        return False
    title = common.norm(sel.xpath("//title/text()").get() or "")
    return title.lower().startswith("find an action")


def is_action_index_page(sel) -> bool:
    return bool(sel.xpath("//table[@id='table_actions_list']") and common.has_footer(sel))


def parse_action_index(sel) -> ActionIndexPage:
    table = sel.xpath("//table[@id='table_actions_list']")
    root = table[0] if table else sel
    text_all = " ".join(sel.xpath("//text()").getall())
    total_match = _RECORDS_FOUND.search(text_all)
    total = int(total_match.group(1).replace(",", "")) if total_match else None
    page_match = _SHOWING_PAGE.search(text_all)
    page = int(page_match.group(1)) if page_match else None
    pages = int(page_match.group(2)) if page_match else None

    rows: list[ActionIndexRow] = []
    for tr in root.xpath("./tr"):
        battle_cell = _td_class(tr, "col_battle")
        if battle_cell is None:
            continue
        date_cell = _td_class(tr, "col_battle_dates")
        spans = date_cell.xpath("./span[@title]") if date_cell is not None else []
        date = (
            parse_td_date(common.node_text(spans[0]), spans[0].attrib.get("title"))
            if spans
            else None
        )
        end_date = (
            parse_td_date(common.node_text(spans[1]), spans[1].attrib.get("title"))
            if len(spans) > 1
            else None
        )
        type_cell = _td_class(tr, "col_action_type")
        war_cell = _td_class(tr, "col_war")
        war_ids = common.link_ids(war_cell, "show_war") if war_cell is not None else []
        war_links = (
            [link for link in common.links(war_cell) if link.kind == "show_war"]
            if war_cell is not None
            else []
        )
        battle_ids = common.link_ids(battle_cell, "show_battle")
        rows.append(
            ActionIndexRow(
                battle_id=battle_ids[0] if battle_ids else None,
                name=common.node_text(battle_cell),
                date=date,
                end_date=end_date,
                action_type=common.node_text(type_cell) if type_cell is not None else None,
                war_id=war_ids[0] if war_ids else None,
                war_text=war_links[0].text if war_links else None,
                cells=[common.node_text(td) for td in tr.xpath("./td")],
                page=page,
            )
        )
    return ActionIndexPage(rows=rows, page=page, pages=pages, total=total)


def _first_line(strong) -> str:
    """The strong's text up to the first ``<br>`` (the date line)."""
    root = strong.root
    parts = [root.text or ""]
    for child in root:
        if child.tag == "br":
            break
        parts.append(child.text_content())
        parts.append(child.tail or "")
    return common.norm(parts)


def _labelled_span(strong, prefix: str):
    for span in strong.xpath(".//span"):
        if common.visible_text(span).startswith(prefix):
            return span
    return None


def _parse_header(datacol, record: ActionRecord) -> None:
    header_divs = datacol.xpath(
        "./div[.//strong][following-sibling::table[@id='table_action_info']]"
    )
    if not header_divs:
        header_divs = datacol.xpath("./div[.//strong]")
    if not header_divs:
        return
    header = header_divs[0]
    record.header_text = common.visible_text(header)
    strongs = header.xpath(".//strong")
    if not strongs:
        return
    strong = strongs[0]
    record.date, record.end_date = parse_long_date(_first_line(strong))

    war_span = _labelled_span(strong, "Part of")
    if war_span is not None:
        war_ids = common.link_ids(war_span, "show_war")
        war_links = [link for link in common.links(war_span) if link.kind == "show_war"]
        record.war_id = war_ids[0] if war_ids else None
        record.war_text = war_links[0].text if war_links else None

    place_span = _labelled_span(strong, "Fought at")
    if place_span is not None:
        record.places = [link for link in common.links(place_span) if link.kind == "show_shipyard"]

    previous = _labelled_span(strong, "Previous action")
    if previous is not None:
        ids = common.link_ids(previous, "show_battle")
        record.previous_battle_id = ids[0] if ids else None
    following = _labelled_span(strong, "Next action")
    if following is not None:
        ids = common.link_ids(following, "show_battle")
        record.next_battle_id = ids[0] if ids else None


def _parse_coordinates(datacol, record: ActionRecord) -> None:
    holders = datacol.xpath(".//div[@id='actionmapholder']")
    if not holders:
        return
    script = "".join(holders[0].xpath(".//text()").getall())
    match = _POSITION.search(script)
    if match:
        record.latitude = float(match.group(1))
        record.longitude = float(match.group(2))


def _blank_or_header(tr) -> bool:
    text = common.norm(tr.xpath(".//text()").getall())
    return text in ("", "\xa0") or text.startswith("Ship Name")


def _parse_participants_table(datacol, record: ActionRecord) -> None:
    table = datacol.xpath(".//table[@id='table_action_info']")
    if not table:
        return
    current_side: int | None = None
    current_division: int | None = None

    for tr in table[0].xpath(".//tr"):
        classes = tr.attrib.get("class") or ""
        if "action_div_notes" in classes:
            note_cells = tr.xpath("./td")
            paragraphs = note_cells[0].xpath(".//p") if note_cells else []
            texts = [common.node_text(p) for p in paragraphs]
            texts = [t for t in texts if t]
            if current_division is not None and texts:
                record.divisions[current_division].notes.extend(texts)
            else:
                record.unknown_rows.extend(common.norm(t)[:200] for t in texts)
            continue

        header_cells = tr.xpath("./th")
        if header_cells:
            cell = header_cells[0]
            h2 = cell.xpath(".//h2")
            if h2:
                side = ActionSide(
                    label=common.visible_text(h2[0]),
                    nation_ids=common.link_ids(h2[0], "show_nation"),
                    commander_ids=common.link_ids(h2[0], "show_crewman"),
                    links=common.links(h2[0]),
                )
                record.sides.append(side)
                current_side = len(record.sides) - 1
                current_division = None
                continue
            span = cell.xpath(".//span")
            if span:
                division = ActionDivision(
                    side_index=current_side,
                    label=common.visible_text(span[0]),
                    commander_ids=common.link_ids(span[0], "show_crewman"),
                    links=common.links(span[0]),
                )
                record.divisions.append(division)
                current_division = len(record.divisions) - 1
                continue
            continue  # column header or spacer

        cells = tr.xpath("./td")
        if not cells:
            continue
        first = cells[0]
        if first.xpath("self::td[contains(@class,'column2')]"):
            record.participants.append(
                _parse_participant(cells, current_side, current_division)
            )
            continue
        if _blank_or_header(tr):
            continue
        record.unknown_rows.append(common.norm(tr.xpath(".//text()").getall())[:200])


def _parse_participant(cells, side_index: int | None, division_index: int | None) -> Participant:
    ship_cell = cells[0]
    ship_links = [link for link in common.links(ship_cell) if link.kind == "show_ship"]
    if ship_links:
        ship = ship_links[0]
        td_id = ship.id
        ship_label = ship.text
    else:
        ship = None
        td_id = None
        ship_label = common.visible_text(ship_cell, drop_hidden=True)

    commander_cell = cells[1] if len(cells) > 1 else None
    if commander_cell is not None:
        commanders = [link for link in common.links(commander_cell) if link.kind == "show_crewman"]
        commander_text = common.visible_text(commander_cell) or None
    else:
        commanders = []
        commander_text = None

    notes_cell = cells[2] if len(cells) > 2 else None
    notes = common.visible_text(notes_cell) if notes_cell is not None else ""
    flags = (
        [common.norm(s.xpath(".//text()").getall()) for s in notes_cell.xpath(".//strong")]
        if notes_cell is not None
        else []
    )
    flags = [flag for flag in flags if flag]

    return Participant(
        side_index=side_index,
        division_index=division_index,
        td_id=td_id,
        ship_label=ship_label,
        ship=ship,
        commander_ids=[link.id for link in commanders if link.id is not None],
        commander_text=commander_text,
        commanders=commanders,
        notes=notes,
        flags=flags,
    )


def _parse_notes(datacol) -> str | None:
    holders = datacol.xpath(".//div[@id='table_page_notes']")
    if not holders:
        return None
    expr = f".//text()[{common.NOT_TOOLTIP} and not(ancestor::h2)]"
    text = common.norm(holders[0].xpath(expr).getall())
    return text or None


def _parse_unknown_sections(datacol) -> list[str]:
    unknown: list[str] = []
    for h2 in datacol.xpath(".//h2"):
        if h2.xpath("ancestor::table[@id='table_action_info']"):
            continue
        heading = common.visible_text(h2)
        if heading in IGNORED_SECTIONS:
            continue
        unknown.append(heading)
    return unknown


def parse_action(
    sel,
    url: str,
    *,
    fetched_at: str = "",
    content_sha256: str = "",
    parser_version: str = ACTION_PARSER_VERSION,
) -> ActionRecord:
    datacols = sel.xpath("//div[@id='datacol']")
    datacol = datacols[0] if datacols else sel
    record = ActionRecord(
        battle_id=extract_id(url),
        name=common.norm(datacol.xpath(".//h1//text()").getall()),
        url=url,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        parser_version=parser_version,
    )
    _parse_header(datacol, record)
    _parse_coordinates(datacol, record)
    _parse_participants_table(datacol, record)
    record.notes = _parse_notes(datacol)
    record.sources = common.parse_sources(datacol)
    record.unknown_sections = _parse_unknown_sections(datacol)
    return record
