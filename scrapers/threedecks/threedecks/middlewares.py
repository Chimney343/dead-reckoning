"""Wait out Cloudflare, stop on a hard block, never work around either (Plan 4.2, rule 5).

A 429 or a Cloudflare challenge page pauses the whole crawl for a long cool-off
(``Retry-After`` when it is longer, otherwise ``THREEDECKS_COOLOFF_SECS``,
doubling each time), then retries the same request unchanged: same User-Agent,
no proxy, no challenge solving. A Cloudflare WAF block page (``cf-mitigated:
blocked``, or "Sorry, you have been blocked") or a plain 403 is never waited
out. After ``THREEDECKS_MAX_COOLOFFS`` blocks in a row, or too many blocks
inside the sliding window, the spider closes with reason ``blocked`` and the
page stays pending for the next run.

These statuses are deliberately absent from ``RETRY_HTTP_CODES``: RetryMiddleware
would re-send them within seconds.
"""

from __future__ import annotations

import logging
import time
from collections import deque
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime

from scrapy.exceptions import IgnoreRequest
from scrapy.utils.defer import deferred_from_coro

logger = logging.getLogger(__name__)

RATE_LIMITED = 429
# Markers of a challenge *page*. A bare "challenge-platform" is not one: Cloudflare's
# JavaScript detections inject /cdn-cgi/challenge-platform/scripts/jsd/main.js
# into ordinary pages, which would close the spider on every response.
CHALLENGE_MARKERS = (
    b"just a moment",
    b"cf-chl",
    b"_cf_chl_opt",
    b"/cdn-cgi/challenge-platform/h/",
)
# Markers of a WAF *block* page. "Sorry, you have been blocked" is second-person,
# so it cannot appear in the site's ship-history prose.
BLOCKED_MARKERS = (b"sorry, you have been blocked",)
# A Retry-After longer than this is not waited out in-process; rerun later instead.
MAX_WAIT_SECS = 2 * 60 * 60


def mitigation(response) -> str | None:
    """The ``cf-mitigated`` header, lowercased: "challenge", "blocked", other, or None."""
    value = response.headers.get(b"cf-mitigated")
    if not value:
        return None
    text = value.decode("latin-1").strip().lower()
    return text or None


def is_challenge(response) -> bool:
    """A Cloudflare challenge page, whatever its status."""
    if mitigation(response) == "challenge":
        return True
    body = response.body.lower()
    return any(marker in body for marker in CHALLENGE_MARKERS)


def is_blocked(response) -> bool:
    """A Cloudflare WAF block page, whatever its status (200 included)."""
    if mitigation(response) == "blocked":
        return True
    body = response.body.lower()
    return any(marker in body for marker in BLOCKED_MARKERS)


def retry_after_secs(response) -> float | None:
    """``Retry-After`` in seconds (delta or HTTP date), or ``None``."""
    value = response.headers.get(b"Retry-After")
    if not value:
        return None
    text = value.decode("latin-1").strip()
    if text.isdigit():
        return float(text)
    try:
        when = parsedate_to_datetime(text)
    except (TypeError, ValueError):
        return None
    return max(0.0, (when - datetime.now(UTC)).total_seconds())


def _call_later(delay: float, func) -> None:
    from twisted.internet import reactor

    reactor.callLater(delay, func)


class BlockDetectionMiddleware:
    def __init__(
        self,
        cooloff_secs: float = 900,
        max_cooloffs: int = 3,
        block_window_secs: float = 7200,
        block_window_max: int = 4,
        clock=time.time,
    ) -> None:
        self.cooloff_secs = cooloff_secs
        self.max_cooloffs = max_cooloffs
        self.block_window_secs = block_window_secs
        self.block_window_max = block_window_max
        self.clock = clock
        self.consecutive = 0  # blocks since the last normal response
        self.block_times: deque[float] = deque()  # cooled-off blocks inside the window
        self.call_later = _call_later
        self.crawler = None

    @classmethod
    def from_crawler(cls, crawler):
        settings = crawler.settings
        middleware = cls(
            cooloff_secs=settings.getfloat("THREEDECKS_COOLOFF_SECS", 900),
            max_cooloffs=settings.getint("THREEDECKS_MAX_COOLOFFS", 3),
            block_window_secs=settings.getfloat("THREEDECKS_BLOCK_WINDOW_SECS", 7200),
            block_window_max=settings.getint("THREEDECKS_BLOCK_WINDOW_MAX", 4),
        )
        middleware.crawler = crawler
        return middleware

    def process_response(self, request, response, spider=None):
        # Scrapy 2.19 deprecates the spider argument; keep the crawler instead.
        crawler = self.crawler or spider.crawler
        blocked = is_blocked(response)
        challenge = is_challenge(response)
        if not blocked and not challenge and response.status not in (RATE_LIMITED, 403):
            self.consecutive = 0
            return response

        # A WAF block is a decision, not a challenge: never cooled off.
        wait = None if blocked else self._cooloff_wait(request, response, challenge)
        if wait is not None:
            window = self._record_block()
            if window >= self.block_window_max:
                logger.error(
                    "%d blocks in %.0f min; closing spider with reason 'blocked'. "
                    "Investigate, then resume; do not evade.",
                    window,
                    self.block_window_secs / 60,
                )
                deferred_from_coro(crawler.engine.close_spider_async(reason="blocked"))
                raise IgnoreRequest(f"blocked {window} times in the block window")
            self.consecutive += 1
            logger.warning(
                "%s at %s (status %s); pausing the crawl for %.0f min (cool-off %d of %d), "
                "then retrying the same request unchanged.",
                "Cloudflare challenge" if challenge else "rate limited",
                request.url,
                response.status,
                wait / 60,
                self.consecutive,
                self.max_cooloffs,
            )
            stats = getattr(crawler, "stats", None)
            if stats is not None:
                stats.inc_value("threedecks/cooloff")
                # The heartbeat passes this on, so the watchdog does not mistake
                # a cool-off for a stall.
                stats.set_value("threedecks/cooloff_until", time.time() + wait)
            engine = crawler.engine
            engine.pause()
            self.call_later(wait, engine.unpause)
            return request.replace(dont_filter=True)

        logger.error(
            "%s at %s (status %s); closing spider with reason 'blocked'. "
            "Investigate, then resume; do not evade.",
            "Cloudflare block page" if blocked else "blocked",
            request.url,
            response.status,
        )
        deferred_from_coro(crawler.engine.close_spider_async(reason="blocked"))
        # Dropped here, so RetryMiddleware never re-sends it and no callback or
        # errback records it.
        raise IgnoreRequest(f"blocked at {request.url} (status {response.status})")

    def _record_block(self) -> int:
        """Record a block that will be cooled off; how many fall inside the window.

        ``consecutive`` resets on any normal response, so an alternating
        block/200 pattern never escalates by that counter alone. The window
        counts cooled-off blocks regardless of what is in between.
        """
        now = self.clock()
        while self.block_times and now - self.block_times[0] > self.block_window_secs:
            self.block_times.popleft()
        self.block_times.append(now)
        return len(self.block_times)

    def _cooloff_wait(self, request, response, challenge: bool) -> float | None:
        """Seconds to pause before retrying, or ``None`` to stop the crawl."""
        if not (challenge or response.status == RATE_LIMITED):
            return None  # a plain 403 is an access rule; waiting will not lift it
        if request.url.endswith("/robots.txt"):
            return None  # fetched outside the scheduler, so a pause would not hold it
        if self.consecutive >= self.max_cooloffs:
            return None
        wait = self.cooloff_secs * 2**self.consecutive
        wait = max(wait, retry_after_secs(response) or 0.0)
        return wait if wait <= MAX_WAIT_SECS else None
