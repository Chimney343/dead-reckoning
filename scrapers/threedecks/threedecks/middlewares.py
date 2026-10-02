"""Stop the crawl on a block, never work around it (Plan 4.2, rule 5).

403, 429 and Cloudflare challenge pages close the spider with reason
``blocked``. They are deliberately absent from ``RETRY_HTTP_CODES``: permission
to crawl does not mean permission to evade an access control.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

BLOCK_STATUSES = {403, 429}
CHALLENGE_MARKERS = (b"just a moment", b"cf-chl", b"challenge-platform")


class BlockDetectionMiddleware:
    def process_response(self, request, response, spider):
        if response.status in BLOCK_STATUSES or self._is_challenge(response):
            logger.error(
                "blocked at %s (status %s); closing spider with reason 'blocked'. "
                "Investigate, then resume; do not evade.",
                request.url,
                response.status,
            )
            spider.crawler.engine.close_spider(spider, "blocked")
        return response

    @staticmethod
    def _is_challenge(response) -> bool:
        body = response.body.lower()
        return any(marker in body for marker in CHALLENGE_MARKERS)
