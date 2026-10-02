"""Sections and ``<br>``-delimited span grids.

The ship page is not a table: a section is a block (usually a ``div`` that is a
direct child of ``#datacol``) whose heading is an ``h2``, and its rows are the
sibling nodes between ``<br>`` elements. Two hazards drive this module:

* headings carry a count ("15 Ship Commanders"), so matching strips ``^\\d+\\s+``;
* ``div#ship_complement`` is reused for more than one section, so sections are
  found by heading and bounded by the next heading, never by ``id``.

Node end of a section is the next sibling that itself contains an ``h2``.
"""

from __future__ import annotations

import re

from parsel import Selector

_COUNT_PREFIX = re.compile(r"^\d+\s+")


def _normalize(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip()


def strip_count(text: str) -> str:
    """Drop a leading count from a heading: ``"15 Ship Commanders"`` -> ``"Ship Commanders"``."""
    return _COUNT_PREFIX.sub("", text.strip())


def heading_text(h2) -> str:
    """Normalised full heading text, with the count preserved."""
    element = _element(h2)
    return _normalize(" ".join(element.itertext()))


def _element(scope):
    if isinstance(scope, Selector):
        return scope.root
    if isinstance(scope, (list, tuple)):
        return _element(scope[0])
    if hasattr(scope, "root"):
        return scope.root
    return scope


def _wrap(node) -> Selector:
    if isinstance(node, Selector):
        return node
    return Selector(root=node)


def _contains_h2(element) -> bool:
    return next(element.iter("h2"), None) is not None


def _section_nodes(h2) -> list:
    nodes = list(h2.itersiblings())
    block = h2.getparent()
    if block is not None:
        for sibling in block.itersiblings():
            if _contains_h2(sibling):
                break
            nodes.append(sibling)
    return nodes


def section_by_heading(scope, name: str) -> list[Selector] | None:
    """Return the content nodes of the section whose heading matches ``name``.

    ``name`` may omit the leading count ("Ship Commanders"). Returns ``None``
    when the section is absent. The list includes the ``<br>`` separators, so it
    is meant to be passed to :func:`span_rows`.
    """
    target = strip_count(name)
    root = _element(scope)
    for h2 in root.iter("h2"):
        if strip_count(heading_text(h2)) == target:
            return [_wrap(node) for node in _section_nodes(h2)]
    return None


def span_rows(section) -> list[list[Selector]]:
    """Split a section's nodes on ``<br>`` into rows of element nodes.

    Text-only nodes are dropped: every value on these pages sits inside a
    ``span``, ``td`` or ``th``. Empty rows are dropped too.
    """
    if not section:
        return []
    rows: list[list[Selector]] = [[]]
    for node in section:
        element = _element(node)
        if getattr(element, "tag", None) == "br":
            rows.append([])
            continue
        rows[-1].append(_wrap(node))
    return [row for row in rows if row]
