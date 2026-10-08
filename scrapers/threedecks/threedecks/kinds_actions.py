"""Registers the ``action`` page kind (Task A5).

Kept in its own module so the base spider and the fleets plan never touch the
action kind, and vice versa. Importing this module registers it in
``threedecks.pages.KINDS``; ``spiders/actions.py`` imports it, so it is present
whenever the spiders module loads.
"""

from __future__ import annotations

from threedecks.pages import PageKind, register
from threedecks.parsing.actions import (
    ACTION_PARSER_VERSION,
    is_action_not_found,
    is_action_page,
    parse_action,
)

ACTION = register(
    PageKind(
        "action",
        "show_battle",
        is_action_page,
        is_action_not_found,
        parse_action,
        ACTION_PARSER_VERSION,
    )
)
