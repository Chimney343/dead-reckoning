"""Registers the ``fleet`` page kind (Task FL5).

Kept in its own module so the base spider and the actions plan never touch the
fleet kind, and vice versa. Importing this module registers it in
``threedecks.pages.KINDS``; ``spiders/fleets.py`` imports it, so it is present
whenever the spiders module loads.
"""

from __future__ import annotations

from threedecks.pages import PageKind, register
from threedecks.parsing.fleets import (
    FLEET_PARSER_VERSION,
    is_fleet_not_found,
    is_fleet_page,
    parse_fleet,
)

FLEET = register(
    PageKind(
        "fleet",
        "show_fleet",
        is_fleet_page,
        is_fleet_not_found,
        parse_fleet,
        FLEET_PARSER_VERSION,
    )
)
