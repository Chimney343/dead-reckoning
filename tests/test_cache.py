"""Layer 5: the crash-safe SQLite HTTP cache (Plan 4.3, step 5)."""

from __future__ import annotations

import hashlib

import pytest
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings
from threedecks import cache as cache_module
from threedecks.cache import SqliteCacheStorage


class FakeFingerprinter:
    def fingerprint(self, request):
        digest = hashlib.sha1()
        digest.update(request.method.encode())
        digest.update(request.url.encode())
        digest.update(request.body)
        return digest.digest()


class FakeCrawler:
    def __init__(self):
        self.request_fingerprinter = FakeFingerprinter()


class FakeSpider:
    name = "fake"

    def __init__(self):
        self.crawler = FakeCrawler()


@pytest.fixture
def storage(tmp_path):
    settings = Settings()
    settings.set("HTTPCACHE_DIR", str(tmp_path), priority="default")
    settings.set("HTTPCACHE_EXPIRATION_SECS", 0, priority="default")
    storage = SqliteCacheStorage(settings)
    storage.open_spider(FakeSpider())
    yield storage
    storage.close_spider(FakeSpider())


def make_response(url="https://threedecks.org/index.php?display_type=show_ship&id=1"):
    body = b"<html><table id='ship_base'></table></html>"
    return HtmlResponse(url=url, body=body, encoding="utf-8")


def test_store_and_retrieve_round_trip(storage):
    spider = FakeSpider()
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=1")
    response = make_response()
    storage.store_response(spider, request, response)

    cached = storage.retrieve_response(spider, request)
    assert cached is not None
    assert cached.status == 200
    assert cached.body == response.body
    assert cached.url == response.url
    assert "cache_timestamp" in request.meta


def test_miss_returns_none(storage):
    spider = FakeSpider()
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=2")
    assert storage.retrieve_response(spider, request) is None


def test_post_bodies_are_keyed_separately(storage):
    spider = FakeSpider()
    url = "https://threedecks.org/index.php?display_type=select_capture"
    request_a = Request(url, method="POST", body=b"select_from_nation=7", encoding="utf-8")
    request_b = Request(url, method="POST", body=b"select_from_nation=1", encoding="utf-8")
    storage.store_response(spider, request_a, make_response("https://a/1"))
    storage.store_response(spider, request_b, make_response("https://b/2"))

    assert storage.retrieve_response(spider, request_a).url == "https://a/1"
    assert storage.retrieve_response(spider, request_b).url == "https://b/2"


def test_exception_mid_store_leaves_no_entry(storage, monkeypatch):
    spider = FakeSpider()
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=3")

    def boom(*args, **kwargs):
        raise RuntimeError("disk full")

    monkeypatch.setattr(cache_module.pickle, "dumps", boom)
    with pytest.raises(RuntimeError):
        storage.store_response(spider, request, make_response())
    monkeypatch.undo()
    assert storage.retrieve_response(spider, request) is None


def test_remove_response(storage):
    spider = FakeSpider()
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=4")
    storage.store_response(spider, request, make_response())
    storage.remove_response(spider, request)
    assert storage.retrieve_response(spider, request) is None


def test_reopening_keeps_entries(tmp_path):
    settings = Settings()
    settings.set("HTTPCACHE_DIR", str(tmp_path), priority="default")
    settings.set("HTTPCACHE_EXPIRATION_SECS", 0, priority="default")
    spider = FakeSpider()
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=5")

    first = SqliteCacheStorage(settings)
    first.open_spider(spider)
    first.store_response(spider, request, make_response())
    first.close_spider(spider)

    second = SqliteCacheStorage(settings)
    second.open_spider(spider)
    assert second.retrieve_response(spider, request) is not None
    second.close_spider(spider)


def test_robots_txt_is_never_cached():
    # Rule 1: a cached robots.txt would be obeyed forever, even after it changed.
    from threedecks.cache import ThreeDecksCachePolicy

    policy = ThreeDecksCachePolicy(Settings())
    assert not policy.should_cache_request(Request("https://threedecks.org/robots.txt"))
    assert policy.should_cache_request(
        Request("https://threedecks.org/index.php?display_type=show_ship&id=1")
    )


def test_challenge_pages_are_never_cached():
    # A cached challenge would be replayed to the retry after a cool-off.
    from threedecks.cache import ThreeDecksCachePolicy

    policy = ThreeDecksCachePolicy(Settings())
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=1")
    challenge = HtmlResponse(
        url=request.url, body=b"<title>Just a moment...</title>", encoding="utf-8"
    )
    assert not policy.should_cache_response(challenge, request)
    assert policy.should_cache_response(make_response(), request)


def test_block_pages_are_never_cached():
    # A cached WAF block page (any status, 200 included) would be replayed later.
    from threedecks.cache import ThreeDecksCachePolicy

    policy = ThreeDecksCachePolicy(Settings())
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=1")
    by_body = HtmlResponse(
        url=request.url, body=b"<title>Sorry, you have been blocked</title>", encoding="utf-8"
    )
    by_header = HtmlResponse(
        url=request.url,
        body=b"<html>ok</html>",
        headers={"cf-mitigated": "blocked"},
        encoding="utf-8",
    )
    assert not policy.should_cache_response(by_body, request)
    assert not policy.should_cache_response(by_header, request)


def test_every_cache_commit_is_flushed_to_disk(storage):
    # A power cut must not drop a page whose record is already marked done.
    assert storage._conn.execute("PRAGMA synchronous").fetchone()[0] == 2  # FULL
