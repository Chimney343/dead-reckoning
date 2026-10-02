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
    HistoryEvent,
    LabeledDate,
    LinkRef,
    OfficerRow,
    ShipRecord,
    SourceRef,
    extract_id,
)
from threedecks.parsing.dates import parse_td_date
from threedecks.parsing.grid import heading_text, section_by_heading, span_rows, strip_count

_URL_KIND = re.compile(r"display_type=([a-z_]+)")
_LEADING_DATE = re.compile(r"^(\d{1,2}\.\d{1,2}\.\d{4}|\d{4})")

# Base-row labels the parser knows. Anything else is surfaced in unknown_labels
# so a new fate label (Wrecked, Foundered, ...) is noticed rather than dropped.
KNOWN_LABELS = {
    "Nominal Guns",
    "Nationality",
    "Operator",
    "Ordered",
    "Keel Laid Down",
    "Laid down",
    "Named",
    "Launched",
    "How acquired",
    "Acquired",
    "Shipyard",
    "Builder",
    "Built by",
    "Ship Class",
    "Designed by",
    "Constructor",
    "Category",
    "Ship Type",
    "Sailing Rig",
    "Commissioned",
    "Captured",
    "Sold",
    "Transferred",
    "Returned",
    "Wrecked",
    "Burnt",
    "Foundered",
    "Broken Up",
    "Destroyed",
    "Scuttled",
    "Hulk",
    "Renamed",
    "Previously",
    "Becomes",
    "Fate",
    "Fate Notes",
    "In Service",
    "Out of Service",
    "Displacement",
    "Tons Burthen",
    "Crew",
    "Notes",
}

# Headings that are ship sections or deliberately ignored (comments).
KNOWN_SECTIONS = {
    "Dimensions",
    "Armament",
    "Crew Complement",
    "Service History",
    "Notes on Ship",
    "Sources",
    "Recent comments to other pages",
}

# Rank headings; matched after the leading count is stripped.
_OFFICER_WORDS = re.compile(
    r"(Commander|Officer|Admiral|Captain|Lieutenant|Midshipman|Marine|Warrant|Petty)",
    re.IGNORECASE,
)


def _norm(texts) -> str:
    if isinstance(texts, str):
        texts = [texts]
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def _kind(href: str | None) -> str | None:
    if not href:
        return None
    match = _URL_KIND.search(href)
    return match.group(1) if match else None


def _links(cell) -> list[LinkRef]:
    out: list[LinkRef] = []
    for anchor in cell.xpath(".//a[@href]"):
        href = anchor.xpath("./@href").get()
        out.append(
            LinkRef(
                text=_norm(anchor.xpath(".//text()").getall()),
                href=href,
                id=extract_id(href),
                kind=_kind(href),
            )
        )
    return out


def _int_from_text(text: str) -> int | None:
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def _node_text(node) -> str:
    return _norm(node.xpath(".//text()").getall())


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
        if code is not None:
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
        battle_ids = [
            extract_id(href)
            for href in event_node.xpath(".//a[contains(@href,'show_battle')]/@href").getall()
        ]
        ship_ids = [
            extract_id(href)
            for href in event_node.xpath(".//a[contains(@href,'show_ship')]/@href").getall()
        ]
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
                battle_ids=[i for i in battle_ids if i is not None],
                ship_ids=[i for i in ship_ids if i is not None],
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


def _parse_sources(root) -> list[SourceRef]:
    sources: list[SourceRef] = []
    for div in root.xpath(".//div[@id='source_list']/div"):
        code = _norm(div.xpath("./span[1]//text()").getall()) or None
        title_link = div.xpath(".//a[contains(@href,'show_source')]")
        title = None
        source_id = None
        if title_link:
            title = _norm(title_link[0].xpath(".//text()").getall())
            source_id = extract_id(title_link[0].xpath("./@href").get())
        authors = [
            _norm(a.xpath(".//text()").getall())
            for a in div.xpath(".//a[contains(@href,'show_author')]")
        ]
        type_text = _norm(div.xpath("./span[last()]//text()").getall()) or None
        sources.append(
            SourceRef(
                code=code,
                title=title,
                authors=[a for a in authors if a],
                type=type_text,
                source_id=source_id,
            )
        )
    return sources


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
            text = _norm(value_cell.xpath(".//text()").getall())
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
        LabeledDate(label=item.label, text=item.text, date=item.date)
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
    """A completeness check (Plan 4.3, step 6)."""
    return bool(selector.xpath("//table[@id='ship_base']"))


def is_not_found_page(selector: Selector) -> bool:
    """The signature of a missing ship id: the "Find a ship" page."""
    if is_ship_page(selector):
        return False
    title = _norm(selector.xpath("//title/text()").get() or "")
    return "find a ship" in title.lower()
