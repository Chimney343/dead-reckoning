"""Location-phrase extraction from loss text (plan section 5.5)."""

from __future__ import annotations

import re

_LOSS_VERB = (
    r"(?:was\s+)?(?:wrecked|foundered|sank|sunk|stranded|driven ashore|ran aground"
    r"|cast away|lost|destroyed|burnt|burned|captured|went down|abandoned)"
)
_PREP = r"(?:at|on|near|off|in|by)"
_MAIN = re.compile(rf"\b{_LOSS_VERB}\b[\s,]+({_PREP}\s+.+)", re.IGNORECASE)
_NAUTICAL = re.compile(
    r"\d+(?:\.\d+)?\s+nautical miles?\b[^.;(]*?\bof\s+([^.;(]+)", re.IGNORECASE
)
_TRAILING_ON_DATE = re.compile(r"\s+on\s+\d[\d./-]*.*$", re.IGNORECASE)
_BAD_REST = re.compile(
    r"^(?:a|an|the)\s+(?:storm|gale|hurricane|typhoon|tempest|cyclone|squall|fire|ice"
    r"|action|battle|collision|voyage|passage|way)\b",
    re.IGNORECASE,
)
_LEADING_PREP = re.compile(rf"^{_PREP}\s+", re.IGNORECASE)


def _clean(phrase: str) -> str | None:
    phrase = re.split(r"[.;(]", phrase, maxsplit=1)[0]
    phrase = phrase.strip().strip(",;.")
    return phrase or None


def extract_place(text: object) -> str | None:
    """Return the first loss location phrase, or ``None``."""
    if text is None:
        return None
    source = str(text)
    if not source:
        return None

    nautical = _NAUTICAL.search(source)
    if nautical:
        cleaned = _clean(nautical.group(1))
        if cleaned:
            return cleaned

    match = _MAIN.search(source)
    if not match:
        return None
    phrase = match.group(1)
    phrase = _TRAILING_ON_DATE.sub("", phrase)
    rest = _LEADING_PREP.sub("", phrase)
    if _BAD_REST.search(rest):
        return None
    return _clean(phrase)
