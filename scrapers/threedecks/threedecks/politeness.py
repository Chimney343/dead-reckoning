"""Settings that carry the site owner's rate condition and rule 2 (Plan 2.3).

Scripts that take ``-s KEY=VALUE`` overrides refuse to loosen these against the
real site. A local test site (the smoke and crawl tests) may override anything.
"""

from __future__ import annotations

import argparse
from urllib.parse import urlparse

PROTECTED = frozenset(
    {
        "AUTOTHROTTLE_ENABLED",
        "AUTOTHROTTLE_START_DELAY",
        "AUTOTHROTTLE_TARGET_CONCURRENCY",
        "CONCURRENT_REQUESTS",
        "CONCURRENT_REQUESTS_PER_DOMAIN",
        "DEFAULT_REQUEST_HEADERS",
        "DOWNLOAD_DELAY",
        "DOWNLOAD_DELAY_JITTER",
        "RETRY_HTTP_CODES",
        "ROBOTSTXT_OBEY",
        "THREEDECKS_COOLOFF_SECS",
        "USER_AGENT",
    }
)
LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})


def refused_overrides(overrides, base_url: str) -> list[str]:
    """The protected settings in ``overrides``, unless ``base_url`` is a local test site."""
    if urlparse(base_url).hostname in LOCAL_HOSTS:
        return []
    return sorted(PROTECTED & set(overrides))


def refusal_message(refused: list[str], base_url: str) -> str:
    return (
        f"error: refusing to override {', '.join(refused)} against {base_url}; "
        "the 5 s rate is the site owner's condition (rule 1)"
    )


def parse_override(text: str) -> tuple[str, str]:
    """argparse type for ``-s KEY=VALUE``."""
    key, sep, value = text.partition("=")
    if not sep or not key:
        raise argparse.ArgumentTypeError(f"expected KEY=VALUE, got {text!r}")
    return key, value
