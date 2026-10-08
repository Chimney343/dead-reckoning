"""Form payloads shared by the spiders and the fixture fetcher (Task A6)."""

from __future__ import annotations


def action_index_form(page: int) -> dict:
    """The ``action_selector`` form as its "Next" button submits it: no filters."""
    return {
        "formid": "action_selector",
        "page": str(page),
        "limit": "50",
        "battle_name": "",
        "type": "0",
        "war": "0",
        "date": "",
        "date_yy": "0000",
        "date_mm": "00",
        "date_dd": "00",
    }
