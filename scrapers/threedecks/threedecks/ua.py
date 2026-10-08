"""Identifiable User-Agent for the Three Decks crawler (rule 2).

The contact address is read from ``THREEDECKS_CONTACT`` and is never
hard-coded. There is no User-Agent rotation: one honest agent, one contact.
"""

from __future__ import annotations

import os

PROJECT_URL = "https://github.com/Chimney343/dead-reckoning"
PLACEHOLDER = "contact-unset"
MISSING_CONTACT_HELP = (
    "THREEDECKS_CONTACT is not set, so the crawler would not be identifiable (rule 2). "
    'Set it first, e.g. in PowerShell: $env:THREEDECKS_CONTACT = "you@example.org"'
)


class MissingContactError(RuntimeError):
    """Raised before any request when the User-Agent carries no contact address."""


def contact(environ: dict[str, str] | None = None) -> str:
    """Return ``THREEDECKS_CONTACT`` from the environment, or ``""``."""
    environ = os.environ if environ is None else environ
    return environ.get("THREEDECKS_CONTACT", "").strip()


def build_user_agent(environ: dict[str, str] | None = None) -> str:
    """Build the one User-Agent this project ever sends."""
    who = contact(environ) or PLACEHOLDER
    return f"dead-reckoning/0.1 (+{PROJECT_URL}; {who})"


def require_contact(user_agent: str, environ: dict[str, str] | None = None) -> str:
    """Return the contact address, or raise if ``user_agent`` would go out without it."""
    who = contact(environ)
    if not who or who not in user_agent:
        raise MissingContactError(MISSING_CONTACT_HELP)
    return who
