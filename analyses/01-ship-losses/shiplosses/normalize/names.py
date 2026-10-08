"""Ship-name normalisation (plan section 3.1)."""

from __future__ import annotations

import re

from unidecode import unidecode

_PREFIX = re.compile(
    r"^(?:(?:h\.?m\.?s\.?s|u\.?s\.?s|h\.?m\.?a\.?s|h\.?m\.?n\.?z\.?s|h\.?m\.?c\.?s"
    r"|h\.?m\.?a\.?v|h\.?m\.?s\.?m|s\.?m\.?s|s\.?s|m\.?v|h\.?m\.?s|r\.?f\.?a)\b[\s.,]*)+",
    re.IGNORECASE,
)
_YEAR_SUFFIX = re.compile(r"\s*(?:[-–—]\s*)?1[4-9]\d\d\s*$")
_PAREN = re.compile(r"\((?:probably|probable|possibly)\)", re.IGNORECASE)


def normalize_name(raw: object) -> str:
    """Lower-case, transliterate and strip prefixes/quotes/suffixes."""
    if raw is None:
        return ""
    text = unidecode(str(raw)).replace("\xa0", " ")
    text = text.replace('"', " ").replace("'", " ")
    text = _PAREN.sub(" ", text)
    text = _PREFIX.sub("", text)
    text = _YEAR_SUFFIX.sub("", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip(" .,-").casefold()
