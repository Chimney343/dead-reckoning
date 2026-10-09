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
    # The hover card's lines: a crewman's nation, roles and service years, or a
    # linked ship's years, guns and type. Kept apart from the visible text.
    tooltip: list[str] = field(default_factory=list)


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
    category: str | None = None  # see parsing.ship_page.LABEL_CATEGORIES


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
class FleetRow:
    """One row of the "Fleets" table: a fleet the ship served in."""

    dates: str | None = None
    from_date: TDDate | None = None
    to_date: TDDate | None = None
    fleet_id: int | None = None
    fleet_name: str | None = None
    commander_id: int | None = None
    commander_name: str | None = None
    source_code: str | None = None


@dataclass
class HistoryEvent:
    text: str
    date: TDDate | None = None
    battle_ids: list[int] = field(default_factory=list)
    ship_ids: list[int] = field(default_factory=list)
    shipyard_ids: list[int] = field(default_factory=list)  # yards and places
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
    fleets: list[FleetRow] = field(default_factory=list)
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


# --- actions (Three Decks actions plan, 4.1) --------------------------------


@dataclass
class ActionIndexRow:
    """One row of the action index (``select_action``)."""

    battle_id: int | None
    name: str
    date: TDDate | None = None
    end_date: TDDate | None = None
    action_type: str | None = None  # only the index carries the type
    war_id: int | None = None
    war_text: str | None = None
    cells: list[str] = field(default_factory=list)  # lossless row text
    page: int | None = None


@dataclass
class ActionIndexPage:
    rows: list[ActionIndexRow] = field(default_factory=list)
    page: int | None = None
    pages: int | None = None
    total: int | None = None


@dataclass
class ActionSide:
    label: str
    nation_ids: list[int] = field(default_factory=list)
    commander_ids: list[int] = field(default_factory=list)
    links: list[LinkRef] = field(default_factory=list)  # hover-card lines in LinkRef.tooltip


@dataclass
class ActionDivision:
    side_index: int | None = None
    label: str = ""
    commander_ids: list[int] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)  # tr.action_div_notes paragraphs
    links: list[LinkRef] = field(default_factory=list)


@dataclass
class Participant:
    side_index: int | None = None
    division_index: int | None = None
    td_id: int | None = None  # None when the row names a ship without a link
    ship_label: str = ""
    ship: LinkRef | None = None
    commander_ids: list[int] = field(default_factory=list)
    commander_text: str | None = None
    commanders: list[LinkRef] = field(default_factory=list)
    notes: str = ""
    flags: list[str] = field(default_factory=list)  # <strong> texts in notes


@dataclass
class ActionRecord:
    battle_id: int | None = None
    name: str = ""
    header_text: str = ""
    date: TDDate | None = None
    end_date: TDDate | None = None
    war_id: int | None = None
    war_text: str | None = None
    places: list[LinkRef] = field(default_factory=list)  # "Fought at" show_shipyard links
    previous_battle_id: int | None = None
    next_battle_id: int | None = None
    latitude: float | None = None
    longitude: float | None = None
    sides: list[ActionSide] = field(default_factory=list)
    divisions: list[ActionDivision] = field(default_factory=list)
    participants: list[Participant] = field(default_factory=list)
    notes: str | None = None
    sources: list[SourceRef] = field(default_factory=list)
    unknown_rows: list[str] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)
    url: str = ""
    fetched_at: str = ""
    content_sha256: str = ""
    parser_version: str = ""


# --- fleets (Three Decks fleets plan, 4.1) ----------------------------------


@dataclass
class FleetIndexRow:
    """One row of the fleet-list index (``show_fleetlist``)."""

    fleet_id: int | None
    name: str
    date_from: TDDate | None = None
    date_to: TDDate | None = None
    nation_id: int | None = None
    nation_text: str = ""
    commander_ids: list[int] = field(default_factory=list)
    commanders: list[LinkRef] = field(default_factory=list)  # hover-card lines in LinkRef.tooltip
    cells: list[str] = field(default_factory=list)  # lossless, the 5 cells' visible text


@dataclass
class FleetShip:
    """One row of a fleet page's ships table."""

    td_id: int | None
    ship_label: str
    ship: LinkRef | None = None  # tooltip: ["1787-1814", "British 74 Gun", ...]
    joined: TDDate | None = None
    left: TDDate | None = None
    commander_ids: list[int] = field(default_factory=list)
    commander_text: str | None = None
    commanders: list[LinkRef] = field(default_factory=list)
    notes: str = ""
    cells: list[str] = field(default_factory=list)  # lossless, every td's visible text


@dataclass
class FleetEvent:
    """One dated row of a fleet page's event log."""

    date: TDDate | None
    text: str
    ship_ids: list[int] = field(default_factory=list)
    place_ids: list[int] = field(default_factory=list)
    battle_ids: list[int] = field(default_factory=list)  # ids only; never followed
    links: list[LinkRef] = field(default_factory=list)
    source_code: str | None = None


@dataclass
class FleetRecord:
    fleet_id: int
    name: str
    base_rows: list[BaseRow] = field(default_factory=list)
    commander_ids: list[int] = field(default_factory=list)
    formed: TDDate | None = None
    disbanded: TDDate | None = None
    introduction: str | None = None
    ships: list[FleetShip] = field(default_factory=list)
    events: list[FleetEvent] = field(default_factory=list)
    sources: list[SourceRef] = field(default_factory=list)
    unknown_labels: list[str] = field(default_factory=list)
    unknown_sections: list[str] = field(default_factory=list)
    url: str = ""
    fetched_at: str = ""
    content_sha256: str = ""
    parser_version: str = ""
