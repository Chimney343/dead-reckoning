"""Page-kind registry: one entry per entity page type (Task S4).

The base spider's callback, error handling and completeness logic are the same
whatever the page; only the URL ``display_type``, the completeness signature and
the parser differ. A :class:`PageKind` bundles those, and ``KINDS`` maps a short
name (``ship``, later ``action`` / ``fleet``) to it. Each new crawler registers
its own kind, so the base stays free of any one page's markup.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from parsel import Selector

from threedecks import PARSER_VERSION
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship


@dataclass(frozen=True)
class PageKind:
    name: str
    display_type: str
    is_page: Callable[[Selector], bool]  # includes the footer check (common.has_footer)
    is_not_found: Callable[[Selector], bool]
    parse: Callable[..., object]
    parser_version: str


KINDS: dict[str, PageKind] = {}


def register(kind: PageKind) -> PageKind:
    """Add a kind to the registry. Idempotent: registering twice is harmless."""
    KINDS[kind.name] = kind
    return kind


SHIP = register(
    PageKind(
        "ship",
        "show_ship",
        is_ship_page,
        is_not_found_page,
        parse_ship,
        PARSER_VERSION,
    )
)
