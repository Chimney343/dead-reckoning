"""Parsers for the fleet-list index and fleet pages (Three Decks fleets plan 3).

Extraction is scoped to ``div#datacol`` so the sidebars and the comment table
(which is full of ``a.shiplink``) can never leak into a record. Visible text
never contains hover-card text; the card's lines stay in ``LinkRef.tooltip``.

The fleet-list index's ``tbody`` holds its cells flat, with no ``<tr>`` rows, so
its cells are read in document order and grouped in fives. The fleet page is
three ``table.column8`` elements recognised by shape, never by position.
"""

from __future__ import annotations

from threedecks.items import (
    BaseRow,
    FleetEvent,
    FleetIndexRow,
    FleetRecord,
    FleetShip,
    LinkRef,
    extract_id,
)
from threedecks.parsing import common
from threedecks.parsing.dates import TDDate, parse_td_date

FLEET_PARSER_VERSION = "1"

# The base table's known labels. Anything else is reported, never dropped.
KNOWN_BASE_LABELS = {"Fleet Commander", "Fleet Formed", "Fleet Disbanded"}

# h2 headings that are part of a fleet page or deliberately ignored (comments).
KNOWN_SECTIONS = {"Introduction", "Sources", "Recent comments to other pages"}

_CLASS_COLUMN1 = "column1"
_CLASS_COLUMN2 = "column2"


def _datacol(sel):
    datacol = sel.xpath("//div[@id='datacol']")
    return datacol[0] if datacol else sel


def _has_class(node, name: str) -> bool:
    classes = (node.attrib.get("class") or "").split()
    return name in classes


def _content_tables(root) -> list:
    """Every ``table.column8`` in ``#datacol`` except the comments table."""
    return [
        table
        for table in root.xpath(".//table[contains(@class,'column8')]")
        if table.attrib.get("id") != "comment_list_table"
    ]


def _th_texts(table) -> list[str]:
    return [common.visible_text(th) for th in table.xpath(".//th")]


def _first_cell_labels(table) -> set[str]:
    labels: set[str] = set()
    for tr in table.xpath(".//tr"):
        cells = tr.xpath("./td")
        if cells:
            labels.add(common.visible_text(cells[0]))
    return labels


def _cell_date(cell) -> TDDate | None:
    spans = cell.xpath(".//span[@title]")
    if spans:
        return parse_td_date(common.visible_text(spans[0]), spans[0].attrib.get("title"))
    text = common.visible_text(cell)
    return parse_td_date(text) if text else None


def _source_code(tr) -> str | None:
    anchors = tr.xpath("./td[contains(@class,'source_col')]//a")
    if not anchors:
        return None
    return common.norm(anchors[0].xpath(".//text()").getall()) or None


# --- completeness signatures -------------------------------------------------


def is_fleet_page(sel) -> bool:
    """A completeness check: a non-empty h1, the base table and the footer."""
    if not common.has_footer(sel):
        return False
    root = _datacol(sel)
    h1 = root.xpath(".//h1")
    if not h1 or not common.visible_text(h1[0]):
        return False
    return any("Fleet Formed" in _first_cell_labels(table) for table in _content_tables(root))


def is_fleet_not_found(sel) -> bool:
    """A missing fleet id answers directly with the "Fleet details" shell."""
    if is_fleet_page(sel):
        return False
    title = common.norm(sel.xpath("//title/text()").get() or "")
    if title.lower() != "fleet details":
        return False
    root = _datacol(sel)
    h1 = root.xpath(".//h1")
    return not h1 or not common.visible_text(h1[0])


def is_fleetlist_index_page(sel) -> bool:
    """The fleet-list index: an h1 "Fleets", a show_fleet link and the footer."""
    if not common.has_footer(sel):
        return False
    root = _datacol(sel)
    h1 = root.xpath(".//h1")
    if not h1 or common.visible_text(h1[0]) != "Fleets":
        return False
    # A bare substring test would also match show_fleetlist (a prefix); match exactly.
    return any(
        common.link_kind(anchor.attrib.get("href")) == "show_fleet"
        for anchor in root.xpath(".//a[@href]")
    )


# --- the fleet-list index ----------------------------------------------------


def parse_fleet_index(sel) -> list[FleetIndexRow]:
    """Parse the flat-cell fleet-list index, grouping the cells in fives."""
    root = _datacol(sel)
    tables = root.xpath(".//table")
    table = tables[0] if tables else root
    # The tbody holds the cells directly (no tr); the tr/td alternative keeps
    # this working if the site ever adds row tags.
    cells = table.xpath("./tbody/td | ./tbody/tr/td")
    rows: list[FleetIndexRow] = []
    width = 5
    complete = len(cells) - (len(cells) % width)
    for start in range(0, complete, width):
        chunk = cells[start : start + width]
        date_from = _cell_date(chunk[0])
        date_to = _cell_date(chunk[1])
        nation_ids = common.link_ids(chunk[2], "show_nation")
        fleet_ids = common.link_ids(chunk[3], "show_fleet")
        commanders = [link for link in common.links(chunk[4]) if link.kind == "show_crewman"]
        rows.append(
            FleetIndexRow(
                fleet_id=fleet_ids[0] if fleet_ids else None,
                name=common.visible_text(chunk[3]),
                date_from=date_from,
                date_to=date_to,
                nation_id=nation_ids[0] if nation_ids else None,
                nation_text=common.visible_text(chunk[2]),
                commander_ids=[link.id for link in commanders if link.id is not None],
                commanders=commanders,
                cells=[common.visible_text(cell) for cell in chunk],
            )
        )
    if len(cells) % width:
        raise ValueError(f"fleet-list index cell count {len(cells)} is not a multiple of {width}")
    return rows


# --- a fleet page ------------------------------------------------------------


def _parse_base_table(table, record: FleetRecord) -> None:
    for tr in table.xpath(".//tr"):
        cells = tr.xpath("./td")
        if not cells:
            continue
        label = common.visible_text(cells[0])
        if not label:
            continue
        value_cells = [
            cell for cell in cells[1:] if not _has_class(cell, "source_col")
        ]
        spans = tr.xpath(".//span[@title]")
        parsed = (
            parse_td_date(common.visible_text(spans[0]), spans[0].attrib.get("title"))
            if spans
            else None
        )
        date = parsed if parsed is not None and parsed.precision is not None else None
        links: list[LinkRef] = [link for cell in value_cells for link in common.links(cell)]
        record.base_rows.append(
            BaseRow(
                label=label,
                text=common.norm([common.visible_text(cell) for cell in value_cells]),
                links=links,
                date=date,
                source_code=_source_code(tr),
            )
        )
        if label == "Fleet Commander":
            record.commander_ids = common.link_ids(tr, "show_crewman")
        elif label == "Fleet Formed":
            record.formed = date
        elif label == "Fleet Disbanded":
            record.disbanded = date
        else:
            record.unknown_labels.append(label)


def _parse_ship_row(tr) -> FleetShip:
    cells = tr.xpath("./td")
    ship_links = [link for link in common.links(tr) if link.kind == "show_ship"]
    ship = ship_links[0] if ship_links else None

    column1 = [cell for cell in cells if _has_class(cell, _CLASS_COLUMN1)]
    joined = _cell_date(column1[0]) if column1 else None
    left = _cell_date(column1[1]) if len(column1) > 1 else None

    column2 = [cell for cell in cells if _has_class(cell, _CLASS_COLUMN2)]
    commander_cell = next(
        (cell for cell in column2 if common.link_ids(cell, "show_crewman")), None
    )
    if commander_cell is not None:
        commanders = [link for link in common.links(commander_cell) if link.kind == "show_crewman"]
        commander_ids = [link.id for link in commanders if link.id is not None]
        commander_text = common.visible_text(commander_cell) or None
    else:
        commanders, commander_ids, commander_text = [], [], None

    notes = common.visible_text(column2[-1]) if column2 else ""
    return FleetShip(
        td_id=ship.id if ship else None,
        ship_label=ship.text if ship else "",
        ship=ship,
        joined=joined,
        left=left,
        commander_ids=commander_ids,
        commander_text=commander_text,
        commanders=commanders,
        notes=notes,
        cells=[common.visible_text(cell) for cell in cells],
    )


def _parse_event_row(tr) -> FleetEvent:
    cells = tr.xpath("./td")
    date_cell = cells[0] if cells else None
    date: TDDate | None = None
    if date_cell is not None:
        spans = date_cell.xpath(".//span[contains(@class,'date_field')]")
        if spans:
            date = parse_td_date(common.visible_text(spans[0]), spans[0].attrib.get("title"))
        else:
            text = common.visible_text(date_cell)
            date = parse_td_date(text) if text else None

    info = tr.xpath("./td[contains(@class,'col_info_text')]")
    info_cell = info[0] if info else None
    return FleetEvent(
        date=date,
        text=common.visible_text(info_cell) if info_cell is not None else "",
        ship_ids=common.link_ids(info_cell, "show_ship") if info_cell is not None else [],
        place_ids=common.link_ids(info_cell, "show_shipyard") if info_cell is not None else [],
        battle_ids=common.link_ids(info_cell, "show_battle") if info_cell is not None else [],
        links=common.links(info_cell) if info_cell is not None else [],
        source_code=_source_code(tr),
    )


def _parse_introduction(root) -> str | None:
    heads = [
        h2 for h2 in root.xpath(".//h2") if common.visible_text(h2) == "Introduction"
    ]
    if not heads:
        return None
    paragraphs: list[str] = []
    for sibling in heads[0].xpath("following-sibling::*"):
        tag = sibling.root.tag
        if tag in ("table", "h2"):
            break
        if tag == "p":
            paragraphs.append(common.visible_text(sibling))
    return common.norm(paragraphs) or None


def _parse_unknown_sections(root) -> list[str]:
    unknown: list[str] = []
    for h2 in root.xpath(".//h2"):
        heading = common.visible_text(h2)
        if heading and heading not in KNOWN_SECTIONS:
            unknown.append(heading)
    return unknown


def parse_fleet(
    sel,
    url: str,
    *,
    fetched_at: str = "",
    content_sha256: str = "",
    parser_version: str = FLEET_PARSER_VERSION,
) -> FleetRecord:
    """Parse a fleet page into a :class:`FleetRecord`."""
    root = _datacol(sel)
    record = FleetRecord(
        fleet_id=extract_id(url) or 0,
        name=common.norm(root.xpath(".//h1//text()").getall()),
        introduction=_parse_introduction(root),
        sources=common.parse_sources(root),
        unknown_sections=_parse_unknown_sections(root),
        url=url,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        parser_version=parser_version,
    )
    for table in _content_tables(root):
        labels = _first_cell_labels(table)
        headers = _th_texts(table)
        if "Fleet Formed" in labels:
            _parse_base_table(table, record)
        elif "Ship" in headers and "Joined" in headers:
            record.ships = [
                _parse_ship_row(tr) for tr in table.xpath("./tbody/tr") if tr.xpath("./td")
            ]
        elif "Date" in headers and "Event" in headers:
            record.events = [
                _parse_event_row(tr) for tr in table.xpath("./tbody/tr") if tr.xpath("./td")
            ]
        else:
            first = headers[0] if headers else common.visible_text(table.xpath(".//td[1]")[0])
            record.unknown_sections.append(f"table: {first}")
    return record
