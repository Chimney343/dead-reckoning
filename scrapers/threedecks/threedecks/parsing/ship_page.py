"""Parser for a Three Decks ship page (Plan 3.2, 4.1).

Extraction is scoped to ``div#datacol`` so the sidebars and the comment table,
which are full of ``a.shiplink``, can never leak into a record. Base rows are
kept losslessly; typed fields, lifecycle dates and the section grids are derived
from them. ``div#ship_complement`` is reused for Crew Complement and Service
History, so sections are always found by heading (see :mod:`threedecks.parsing.grid`).
"""

from __future__ import annotations

import re

from parsel import Selector

from threedecks import PARSER_VERSION
from threedecks.items import (
    ArmamentSet,
    BaseRow,
    ComplementRow,
    DimensionSet,
    FleetRow,
    HistoryEvent,
    LabeledDate,
    LinkRef,
    OfficerRow,
    ShipRecord,
    extract_id,
)
from threedecks.parsing import common
from threedecks.parsing.dates import parse_td_date
from threedecks.parsing.grid import heading_text, section_by_heading, span_rows, strip_count

# The shared text and link helpers, with their old private names kept as aliases
# so nothing that grew around the ship parser breaks (Task S2).
_norm = common.norm
_kind = common.link_kind
_tooltip_lines = common.tooltip_lines
_links = common.links
_link_ids = common.link_ids
_node_text = common.node_text
_int_from_text = common.int_from_text
_parse_sources = common.parse_sources
_NOT_TOOLTIP = common.NOT_TOOLTIP
_VISIBLE_TEXT = common.VISIBLE_TEXT
_VISIBLE_LINKS = common.VISIBLE_LINKS

_LEADING_DATE = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{4}|\d{4})")

# What each base-row label says about the ship. The loss-event build keys on
# these: "captured" and "lost" end a Spanish service record; "disposed" and
# "transferred" end it without a loss. A label missing here is reported in
# unknown_labels (the row itself is always kept) so it can be added.
LABEL_CATEGORIES = {
    "Nominal Guns": "attribute",
    "Nationality": "attribute",
    "Operator": "attribute",
    "Category": "attribute",
    "Ship Type": "attribute",
    "Sailing Rig": "attribute",
    "Ship Class": "attribute",
    "National Rate": "attribute",
    "Home Port": "attribute",
    "Displacement": "attribute",
    "Tons Burthen": "attribute",
    "Crew": "attribute",
    "Notes": "attribute",
    "Fate": "attribute",
    "Fate Notes": "attribute",
    "Ordered": "built",
    "Keel Laid Down": "built",
    "Laid down": "built",
    "Named": "built",
    "Launched": "built",
    "Shipyard": "built",
    "Builder": "built",
    "Built by": "built",
    "Designed by": "built",
    "Constructor": "built",
    "Commissioned": "built",
    "First Commissioned": "built",
    "How acquired": "acquired",
    "Acquired": "acquired",
    "Purchased": "acquired",
    "Hired": "acquired",
    "Bought by the Navy": "acquired",
    "Requisitioned": "acquired",
    "Captured": "captured",
    "Captured and burnt": "captured",
    "Transferred": "transferred",
    "Transfered": "transferred",
    "Presented": "transferred",
    "Given Away": "transferred",
    "Returned": "transferred",
    "Returned to Owners": "transferred",
    "In Service": "service",
    "Out of Service": "service",
    "Renamed": "service",
    "Razeed": "service",
    "Hulk": "service",
    "Hulked": "service",
    "Disarmed": "service",
    "Mutinied": "service",
    "Rerated": "service",
    "First Mentioned": "attested",
    "Last Mentioned": "attested",
    "Last known": "attested",
    "Extant": "attested",
    "Wrecked": "lost",
    "Burnt": "lost",
    "Burnt to avoid capture": "lost",
    "Foundered": "lost",
    "Destroyed": "lost",
    "Scuttled": "lost",
    "Blown Up": "lost",
    "Sunk in Action": "lost",
    "Expended as Fireship": "lost",
    "Beached": "lost",
    "Abandoned": "lost",
    "Burnt in Action": "lost",
    "Sunk to avoid capture": "lost",
    "Sold": "disposed",
    "Sold for Break Up": "disposed",
    "Broken Up": "disposed",
    "Broken Up to Rebuild": "disposed",
    "Sunk as Foundation": "disposed",
    "Sunk as Breakwater": "disposed",
    "Sunk as Blockship": "disposed",
    "Condemned": "disposed",
    "Deleted from list": "disposed",
    "Previously": "link",
    "Becomes": "link",
}
KNOWN_LABELS = frozenset(LABEL_CATEGORIES)

# Headings that are ship sections or deliberately ignored (comments).
KNOWN_SECTIONS = {
    "Dimensions",
    "Armament",
    "Crew Complement",
    "Service History",
    "Fleets",
    "Notes on Ship",
    "Sources",
    "Recent comments to other pages",
}

# Rank headings; matched after the leading count is stripped.
_OFFICER_WORDS = re.compile(
    r"(Commander|Officer|Admiral|Captain|Lieutenant|Midshipman|Marine|Warrant|Petty)",
    re.IGNORECASE,
)


def _row_texts(row) -> list[str]:
    return [_node_text(node) for node in row]


def _row_text(row) -> str:
    return _norm(_row_texts(row))


def _anchor_code(row) -> str | None:
    for node in row:
        anchor = node.xpath(".//a[starts-with(@href,'#')]")
        if anchor:
            return _norm(anchor[0].xpath(".//text()").getall())
    return None


def _header_code(row) -> str | None:
    """Source code of a dimension/armament group header, or ``None`` for data."""
    for node in row:
        if "source_col" in (node.root.get("class") or ""):
            return _node_text(node)
        source = node.xpath(".//*[contains(@class,'source_col')]")
        if source:
            return _node_text(source[0])
        anchor = node.xpath(".//a[starts-with(@href,'#')]")
        if anchor:
            return _norm(anchor[0].xpath(".//text()").getall())
    return None


def _has_strong(row) -> bool:
    return any(node.xpath(".//strong") for node in row)


def _grouped_dimensions(rows) -> list[DimensionSet]:
    sets: list[DimensionSet] = []
    current: DimensionSet | None = None
    for row in rows:
        code = _header_code(row)
        # A header names its source when it has one; without one it is still a header.
        if code is not None or _has_strong(row):
            current = DimensionSet(source_code=code)
            sets.append(current)
            continue
        if current is None:
            current = DimensionSet(source_code=None)
            sets.append(current)
        current.rows.append(_row_texts(row))
    return sets


def _grouped_armament(rows) -> list[ArmamentSet]:
    sets: list[ArmamentSet] = []
    current: ArmamentSet | None = None
    for row in rows:
        code = _header_code(row)
        if code is not None:
            date_match = _LEADING_DATE.match(_row_text(row))
            current = ArmamentSet(
                source_code=code, date=date_match.group(1) if date_match else None
            )
            sets.append(current)
            continue
        if current is None:
            current = ArmamentSet(source_code=None)
            sets.append(current)
        current.rows.append(_row_texts(row))
    return sets


def _grouped_complement(rows) -> list[ComplementRow]:
    sets: list[ComplementRow] = []
    current: ComplementRow | None = None
    for row in rows:
        if _has_strong(row):
            continue
        code = _anchor_code(row)
        if current is None or (code is not None and code != current.source_code):
            current = ComplementRow(source_code=code)
            sets.append(current)
        current.rows.append(_row_texts(row))
    return sets


def _parse_history(root) -> list[HistoryEvent]:
    section = section_by_heading(root, "Service History")
    events: list[HistoryEvent] = []
    for row in span_rows(section):
        if not row or _has_strong(row):
            continue
        date_span = row[0]
        tooltip = date_span.xpath(".//*[@title][1]/@title").get()
        date = parse_td_date(_node_text(date_span), tooltip)

        event_node = None
        for node in row:
            if "column7" in (node.root.get("class") or ""):
                event_node = node
                break
        if event_node is None:
            continue
        text = _node_text(event_node)
        source_code = None
        for node in row:
            if node is event_node:
                continue
            code_anchor = node.xpath(".//a[starts-with(@href,'#')]")
            if code_anchor:
                source_code = _norm(code_anchor[0].xpath(".//text()").getall())
        events.append(
            HistoryEvent(
                text=text,
                date=date,
                battle_ids=_link_ids(event_node, "show_battle"),
                ship_ids=_link_ids(event_node, "show_ship"),
                shipyard_ids=_link_ids(event_node, "show_shipyard"),
                source_code=source_code,
            )
        )
    return events


def _officer_rows(section_nodes) -> list[OfficerRow]:
    out: list[OfficerRow] = []
    for node in section_nodes or []:
        if getattr(node.root, "tag", None) != "span":
            continue
        crew = node.xpath(".//a[contains(@href,'show_crewman')]")
        if not crew:
            continue
        cells = node.xpath("./span[contains(@class,'column2')]")
        dates_text = _node_text(cells[0]) if cells else ""
        rank = _node_text(cells[1]) if len(cells) > 1 else None

        named = cells[0].xpath(".//*[@title]") if cells else []
        from_date = to_date = None
        if len(named) >= 2:
            from_date = parse_td_date(
                _norm(named[0].xpath(".//text()").getall()),
                named[0].xpath("./@title").get(),
            )
            to_date = parse_td_date(
                _norm(named[1].xpath(".//text()").getall()),
                named[1].xpath("./@title").get(),
            )
        elif len(named) == 1:
            # "1646" is a single point; "27.1.1720 -" is a range left open.
            from_date = parse_td_date(
                _norm(named[0].xpath(".//text()").getall()),
                named[0].xpath("./@title").get(),
            )
            to_date = None if dates_text.endswith("-") else from_date
        elif " - " in dates_text:
            first, second = dates_text.split(" - ", 1)
            from_date = parse_td_date(first.strip())
            to_date = parse_td_date(second.strip())

        href = crew[0].xpath("./@href").get()
        source = _norm(node.xpath("./span[contains(@class,'column1')]//text()").getall())
        out.append(
            OfficerRow(
                section="",
                dates=dates_text or None,
                rank=rank,
                crewman_id=extract_id(href),
                name=_norm(crew[0].xpath(".//text()").getall()),
                source=source or None,
                from_date=from_date,
                to_date=to_date,
            )
        )
    return out


def _span_date(spans, index: int):
    if len(spans) <= index:
        return None
    return parse_td_date(_node_text(spans[index]), spans[index].attrib.get("title"))


def _parse_fleets(root) -> list[FleetRow]:
    """The "Fleets" table: Dates | Fleet | Fleet Commander | Source.

    The site omits the ``<tr>`` around body rows, so cells are read in document
    order and grouped by the number of column headers.
    """
    tables = root.xpath(".//table[.//h2[normalize-space()='Fleets']]")
    if not tables:
        return []
    width = len(tables[0].xpath("./thead/tr[last()]/th")) or 4
    cells = tables[0].xpath("./tbody//td")
    fleets: list[FleetRow] = []
    for start in range(0, len(cells) - width + 1, width):
        dates, fleet, commander, source = cells[start : start + 4]
        spans = dates.xpath(".//span[@title]")
        fleet_link = fleet.xpath(".//a[contains(@href,'show_fleet')]")
        crew_link = commander.xpath(".//a[contains(@href,'show_crewman')]")
        fleets.append(
            FleetRow(
                dates=_node_text(dates) or None,
                from_date=_span_date(spans, 0),
                to_date=_span_date(spans, 1),
                fleet_id=extract_id(fleet_link[0].attrib.get("href")) if fleet_link else None,
                fleet_name=_node_text(fleet_link[0] if fleet_link else fleet) or None,
                commander_id=extract_id(crew_link[0].attrib.get("href")) if crew_link else None,
                commander_name=_node_text(crew_link[0]) if crew_link else None,
                source_code=_node_text(source) or None,
            )
        )
    return fleets


def _section_text(root, name: str) -> str | None:
    nodes = section_by_heading(root, name)
    if not nodes:
        return None
    text = _norm(_node_text(node) for node in nodes)
    return text or None


def parse_ship(
    selector: Selector,
    url: str,
    *,
    fetched_at: str = "",
    content_sha256: str = "",
    parser_version: str = PARSER_VERSION,
) -> ShipRecord:
    """Parse a ship page into a :class:`ShipRecord`."""
    datacol = selector.xpath("//div[@id='datacol']")
    root = datacol[0] if datacol else selector

    name = _norm(root.xpath(".//h1[contains(@class,'LaunchName')]//text()").getall())
    table = root.xpath(".//table[@id='ship_base']")
    td_id: int | None = None
    base_rows: list[BaseRow] = []
    if table:
        td_id = _int_from_text(
            _norm(table[0].xpath(".//*[contains(@class,'showid')]//text()").getall())
        )
        for tr in table[0].xpath(".//tr"):
            cells = tr.xpath("./td")
            if len(cells) < 2:
                continue
            label = _norm(cells[0].xpath(".//text()").getall())
            value_cell = cells[1]
            text = _node_text(value_cell)
            source_code = None
            if len(cells) > 2:
                source_code = _norm(cells[2].xpath(".//a//text()").getall()) or None
            tooltip = value_cell.xpath(".//*[@title][1]/@title").get()
            parsed = parse_td_date(text, tooltip)
            date = parsed if parsed.precision is not None else None
            base_rows.append(
                BaseRow(
                    label=label,
                    text=text,
                    links=_links(value_cell),
                    date=date,
                    source_code=source_code,
                )
            )

    def row(label: str) -> BaseRow | None:
        lowered = label.lower()
        for item in base_rows:
            if item.label.lower() == lowered:
                return item
        return None

    def link_of(label: str, kind: str) -> LinkRef | None:
        item = row(label)
        if not item:
            return None
        for link in item.links:
            if link.kind == kind:
                return link
        return None

    nation = None
    for item in base_rows:
        for link in item.links:
            if link.kind == "show_nation":
                nation = link
                break
        if nation:
            break
    ship_class = None
    for item in base_rows:
        for link in item.links:
            if link.kind == "show_class":
                ship_class = link
                break
        if ship_class:
            break

    shipyards: list[LinkRef] = []
    yard_row = row("Shipyard")
    if yard_row:
        shipyards = [link for link in yard_row.links if link.kind == "show_shipyard"]

    def crewman_links(label: str) -> list[LinkRef]:
        item = row(label)
        if not item:
            return []
        return [link for link in item.links if link.kind == "show_crewman"]

    designers = crewman_links("Designed by")
    constructors = crewman_links("Constructor")

    def ship_ids(label: str) -> list[int]:
        item = row(label)
        if not item:
            return []
        return [
            link.id
            for link in item.links
            if link.kind == "show_ship" and link.id is not None
        ]

    lifecycle = [
        LabeledDate(
            label=item.label,
            text=item.text,
            date=item.date,
            category=LABEL_CATEGORIES.get(item.label),
        )
        for item in base_rows
        if item.date is not None
    ]
    unknown_labels = [
        item.label for item in base_rows if item.label and item.label not in KNOWN_LABELS
    ]

    dimensions = _grouped_dimensions(span_rows(section_by_heading(root, "Dimensions")))
    armament = _grouped_armament(span_rows(section_by_heading(root, "Armament")))
    complement = _grouped_complement(span_rows(section_by_heading(root, "Crew Complement")))

    officers: list[OfficerRow] = []
    unknown_sections: list[str] = []
    for h2 in root.xpath(".//h2"):
        full = heading_text(h2)
        stripped = strip_count(full)
        if stripped in KNOWN_SECTIONS:
            continue
        section_nodes = section_by_heading(root, stripped)
        if _OFFICER_WORDS.search(stripped) or _has_crewman(section_nodes):
            for officer in _officer_rows(section_nodes):
                officer.section = full
                officers.append(officer)
        else:
            unknown_sections.append(full)

    how_acquired_row = row("How acquired") or row("Acquired")
    ship_type_link = None
    ship_type_row = row("Ship Type")
    if ship_type_row:
        ship_type_link = next(
            (link for link in ship_type_row.links if link.kind == "ship_type"), None
        )

    return ShipRecord(
        td_id=td_id,
        name=name,
        base_rows=base_rows,
        nation_id=nation.id if nation else None,
        nation_name=nation.text if nation else None,
        operator=row("Operator").text if row("Operator") else None,
        nominal_guns=row("Nominal Guns").text if row("Nominal Guns") else None,
        category=row("Category").text if row("Category") else None,
        ship_type=(
            ship_type_link.text
            if ship_type_link
            else (ship_type_row.text if ship_type_row else None)
        ),
        ship_type_id=ship_type_link.id if ship_type_link else None,
        rig=row("Sailing Rig").text if row("Sailing Rig") else None,
        how_acquired=how_acquired_row.text if how_acquired_row else None,
        class_id=ship_class.id if ship_class else None,
        class_name=ship_class.text if ship_class else None,
        shipyards=shipyards,
        designers=designers,
        constructors=constructors,
        previous_td_ids=ship_ids("Previously"),
        next_td_ids=ship_ids("Becomes"),
        lifecycle=lifecycle,
        dimensions=dimensions,
        armament=armament,
        complement=complement,
        officers=officers,
        fleets=_parse_fleets(root),
        history=_parse_history(root),
        sources=_parse_sources(root),
        notes=_section_text(root, "Notes on Ship"),
        unknown_labels=unknown_labels,
        unknown_sections=unknown_sections,
        url=url,
        fetched_at=fetched_at,
        content_sha256=content_sha256,
        parser_version=parser_version,
    )


def _has_crewman(section_nodes) -> bool:
    for node in section_nodes or []:
        if node.xpath(".//a[contains(@href,'show_crewman')]"):
            return True
    return False


def is_ship_page(selector: Selector) -> bool:
    """A completeness check (Plan 4.3, step 6): the base table and the footer.

    The footer comes after ``#datacol``, so a body cut off anywhere in the
    ship's data fails the check.
    """
    return bool(
        selector.xpath("//table[@id='ship_base']") and common.has_footer(selector)
    )


def is_not_found_page(selector: Selector) -> bool:
    """The signature of a missing ship id: the "Find a ship" page."""
    if is_ship_page(selector):
        return False
    title = _norm(selector.xpath("//title/text()").get() or "")
    return "find a ship" in title.lower()
