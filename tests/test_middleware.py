"""Layer 4-6: the block-detection middleware (Plan 4.2).

A 403, a 429 or a Cloudflare challenge page must stop the spider and never be
retried or worked around (rule 5).
"""

from __future__ import annotations

from scrapy.http import HtmlResponse, Request
from threedecks.middlewares import BlockDetectionMiddleware


class FakeEngine:
    def __init__(self):
        self.reasons: list[str] = []

    def close_spider(self, spider, reason):
        self.reasons.append(reason)


class FakeSpider:
    name = "test"

    def __init__(self):
        self.crawler = type("Crawler", (), {"engine": FakeEngine()})()


def response(status=200, body=b"<html>ok</html>"):
    return HtmlResponse(url="https://threedecks.org/x", status=status, body=body)


def test_403_closes_spider():
    spider = FakeSpider()
    BlockDetectionMiddleware().process_response(
        Request("https://threedecks.org/x"), response(403), spider
    )
    assert spider.crawler.engine.reasons == ["blocked"]


def test_429_closes_spider():
    spider = FakeSpider()
    BlockDetectionMiddleware().process_response(
        Request("https://threedecks.org/x"), response(429), spider
    )
    assert spider.crawler.engine.reasons == ["blocked"]


def test_challenge_body_closes_spider():
    spider = FakeSpider()
    body = b"<html><title>Just a moment...</title><div class='cf-chl'></div></html>"
    BlockDetectionMiddleware().process_response(
        Request("https://threedecks.org/x"), response(200, body), spider
    )
    assert spider.crawler.engine.reasons == ["blocked"]


def test_normal_response_passes_through():
    spider = FakeSpider()
    result = BlockDetectionMiddleware().process_response(
        Request("https://threedecks.org/x"), response(200), spider
    )
    assert result.status == 200
    assert spider.crawler.engine.reasons == []
