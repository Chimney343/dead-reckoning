"""Identifiable User-Agent for the Three Decks crawler (rule 2).

The contact address is read from ``THREEDECKS_CONTACT`` and is never
hard-coded. There is no User-Agent rotation: one honest agent, one contact.
"""

from __future__ import annotations

import os

PROJECT_URL = "https://github.com/Chimney343/dead-reckoning"


def contact(environ: dict[str, str] | None = None) -> str:
    """Return ``THREEDECKS_CONTACT`` from the environment, or ``""``."""
    environ = os.environ if environ is None else environ
    return environ.get("THREEDECKS_CONTACT", "").strip()


def build_user_agent(environ: dict[str, str] | None = None) -> str:
    """Build the one User-Agent this project ever sends."""
    who = contact(environ) or "contact-unset"
    return f"dead-reckoning/0.1 (+{PROJECT_URL}; {who})"
