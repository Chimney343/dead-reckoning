"""Dataclass items for the Three Decks scraper (plan section 4.1).

Items are plain dataclasses with no Scrapy dependency, so the parsing layer
stays pure. They are serialised with :func:`dataclasses.asdict` into the state
database rather than through Scrapy feeds (feeds append and can truncate).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from threedecks.parsing.dates import TDDate

_ID_RE = re.compile(r"[?&]id=(\d+)")


def extract_id(href: str | None) -> int | None:
    """Pull the ``id`` query parameter out of a Three Decks URL."""
    if not href:
        return None
    match = _ID_RE.search(href)
    return int(match.group(1)) if match else None


@dataclass
class LinkRef:
    text: str
    href: str | None = None
    id: int | None = None
    kind: str | None = None


@dataclass
class BaseRow:
    """One lossless label/value row from ``table#ship_base``."""

    label: str
    text: str
    links: list[LinkRef] = field(default_factory=list)
    date: TDDate | None = None
    source_code: str | None = None


@dataclass
class LabeledDate:
    """A base row whose value parsed as a date (Launched, Captured, Sold...)."""

    label: str
    text: str
    date: TDDate


@dataclass
class DimensionSet:
    source_code: str | None
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ArmamentSet:
    source_code: str | None
    date: str | None = None
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class ComplementRow:
    source_code: str | None
    rows: list[list[str]] = field(default_factory=list)


@dataclass
class OfficerRow:
    section: str
    dates: str | None = None
    rank: str | None = None
    crewman_id: int | None = None
    name: str | None = None
    source: str | None = None
    from_date: TDDate | None = None
    to_date: TDDate | None = None


@dataclass
class HistoryEvent:
    text: str
    date: TDDate | None = None
    battle_ids: list[int] = field(default_factory=list)
    ship_ids: list[int] = field(default_factory=list)
    source_code: str | None = None


@dataclass
class SourceRef:
    code: str | None
    title: str | None
    authors: list[str] = field(default_factory=list)
    type: str | None = None
    source_id: int | None = None


@dataclass
class ShipRecord:
    td_id: int | None
    name: str
    base_rows: list[BaseRow] = field(default_factory=list)
    nation_id: int | None = None
    nation_name: str | None = None
    operator: str | None = None
    nominal_guns: str | None = None
    category: str | None = None
    ship_type: str | None = None
    ship_type_id: int | None = None
    rig: str | None = None
    how_acquired: str | None = None
    class_id: int | None = None
    class_name: str | None = None
    shipyards: list[LinkRef] = field(default_factory=list)
    designers: list[LinkRef] = field(default_factory=list)
    constructors: list[LinkRef] = field(default_factory=list)
    previous_td_ids: list[int] = field(default_factory=list)
    next_td_ids: list[int] = field(default_factory=list)
    lifecycle: list[LabeledDate] = field(default_factory=list)
    dimensions: list[DimensionSet] = field(default_factory=list)
    armament: list[ArmamentSet] = field(default_factory=list)
    complement: list[ComplementRow] = field(default_factory=list)
    officers: list[OfficerRow] = field(default_factory=list)
    history: list[HistoryEvent] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    notes: str | None = None
    unknown_labels: list[str] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)
    url: str = ""
    fetched_at: str = ""
    content_sha256: str = ""
    parser_version: str = ""


@dataclass
class CaptureRow:
    captured_td_id: int | None
    captured_label: str
    date: TDDate
    captor_td_ids: list[int] = field(default_factory=list)
    captor_text: str = ""
    place_text: str | None = None
    from_nation_id: int | None = None
    by_nation_id: int | None = None
    war_id: int | None = None


@dataclass
class SearchPage:
    ship_ids: list[int] = field(default_factory=list)
    page: int | None = None
    pages: int | None = None
    total: int | None = None
    has_next: bool = False
