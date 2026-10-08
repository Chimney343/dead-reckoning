"""Text, link and footer helpers shared by every Three Decks page parser.

A link's visible text and its hover card (``span.tooltiptext``) are different
things: the card's lines belong in :class:`~threedecks.items.LinkRef.tooltip`,
never in a visible label. These helpers are the single place that separation is
implemented, so every page parser (ship, action, fleet) agrees on it.
"""

from __future__ import annotations

import re

from threedecks.items import LinkRef, SourceRef, extract_id

_URL_KIND = re.compile(r"display_type=([a-z_]+)")

# Linked ships and crewmen carry a hover card (span.tooltiptext) inside the
# cell; its text and links are not part of the cell's own content.
NOT_TOOLTIP = "not(ancestor::span[contains(@class,'tooltiptext')])"
VISIBLE_TEXT = f".//text()[{NOT_TOOLTIP}]"
VISIBLE_LINKS = f".//a[@href][{NOT_TOOLTIP}]"
# Action participant cells prefix their content with <span class="hidden">Name : </span>.
NOT_HIDDEN = "not(ancestor::span[contains(@class,'hidden')])"

FOOTER_XPATH = "//span[@id='copywrite_message'][contains(., 'Copyright')]"


def norm(texts) -> str:
    if isinstance(texts, str):
        texts = [texts]
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def link_kind(href: str | None) -> str | None:
    if not href:
        return None
    match = _URL_KIND.search(href)
    return match.group(1) if match else None


def tooltip_lines(anchor) -> list[str]:
    """The ``<br>``-separated lines of the hover card wrapping ``anchor``."""
    cards = anchor.xpath(
        "./ancestor::div[contains(@class,'tooltip')][1]/span[contains(@class,'tooltiptext')]"
    )
    if not cards:
        return []
    card = cards[0].root
    lines: list[str] = []
    current = [card.text or ""]
    for child in card:
        if child.tag == "br":
            lines.append(norm(current))
            current = []
        else:
            current.append(child.text_content())
        current.append(child.tail or "")
    lines.append(norm(current))
    return [line for line in lines if line]


def links(cell) -> list[LinkRef]:
    out: list[LinkRef] = []
    for anchor in cell.xpath(VISIBLE_LINKS):
        href = anchor.xpath("./@href").get()
        out.append(
            LinkRef(
                text=norm(anchor.xpath(".//text()").getall()),
                href=href,
                id=extract_id(href),
                kind=link_kind(href),
                tooltip=tooltip_lines(anchor),
            )
        )
    return out


def link_ids(node, kind: str) -> list[int]:
    """Ids of the visible links of exactly ``kind`` (``show_ship`` is not ``show_shipyard``)."""
    ids = [
        extract_id(href)
        for href in node.xpath(f"{VISIBLE_LINKS}/@href").getall()
        if link_kind(href) == kind
    ]
    return [i for i in ids if i is not None]


def int_from_text(text: str) -> int | None:
    match = re.search(r"\d+", text or "")
    return int(match.group()) if match else None


def visible_text(node, *, drop_hidden: bool = False) -> str:
    """The node's own visible text: no hover-card text, optionally no ``span.hidden``."""
    if drop_hidden:
        expr = f".//text()[{NOT_TOOLTIP} and {NOT_HIDDEN}]"
    else:
        expr = VISIBLE_TEXT
    return norm(node.xpath(expr).getall())


def node_text(node) -> str:
    return visible_text(node)


def parse_sources(root) -> list[SourceRef]:
    sources: list[SourceRef] = []
    for div in root.xpath(".//div[@id='source_list']/div"):
        code = norm(div.xpath("./span[1]//text()").getall()) or None
        title_link = div.xpath(".//a[contains(@href,'show_source')]")
        title = None
        source_id = None
        if title_link:
            title = norm(title_link[0].xpath(".//text()").getall())
            source_id = extract_id(title_link[0].xpath("./@href").get())
        authors = [
            norm(a.xpath(".//text()").getall())
            for a in div.xpath(".//a[contains(@href,'show_author')]")
        ]
        type_text = norm(div.xpath("./span[last()]//text()").getall()) or None
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


def has_footer(selector) -> bool:
    """The completeness footer every real page ends with (``span#copywrite_message``)."""
    return bool(selector.xpath(FOOTER_XPATH))
