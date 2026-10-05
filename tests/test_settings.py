"""Layer 6: the politeness contract (Plan 4.2, 6).

Loosening any of these must be a deliberate, visible change. Scrapy contracts
(`scrapy check`) are not used because they make live requests.
"""

from __future__ import annotations

import importlib

import pytest
import threedecks.settings as settings
from threedecks.ua import MissingContactError, build_user_agent, require_contact


def reloaded(monkeypatch, contact="contact@example.org"):
    monkeypatch.setenv("THREEDECKS_CONTACT", contact)
    return importlib.reload(settings)


def test_delay_is_at_least_the_robots_crawl_delay(monkeypatch):
    s = reloaded(monkeypatch)
    # The jitter must never take the gap below the owner's 5 s Crawl-delay.
    assert s.DOWNLOAD_DELAY * (1 - s.DOWNLOAD_DELAY_JITTER) >= 5
    assert not hasattr(s, "RANDOMIZE_DOWNLOAD_DELAY")  # deprecated in 2.19
    assert s.AUTOTHROTTLE_START_DELAY >= 6


def test_one_request_at_a_time_and_robots_obeyed(monkeypatch):
    s = reloaded(monkeypatch)
    assert s.CONCURRENT_REQUESTS == 1
    assert s.CONCURRENT_REQUESTS_PER_DOMAIN == 1
    assert s.ROBOTSTXT_OBEY is True


def test_contact_address_is_in_the_user_agent(monkeypatch):
    s = reloaded(monkeypatch, contact="owner@example.org")
    assert "owner@example.org" in s.USER_AGENT
    assert "dead-reckoning" in s.USER_AGENT


def test_block_statuses_are_never_retried(monkeypatch):
    s = reloaded(monkeypatch)
    assert 403 not in s.RETRY_HTTP_CODES
    assert 429 not in s.RETRY_HTTP_CODES


CLOUDFLARE_ORIGIN_ERRORS = [520, 521, 522, 523, 524, 525, 530]


def _cache_policy(s):
    from scrapy.settings import Settings
    from threedecks.cache import ThreeDecksCachePolicy

    return ThreeDecksCachePolicy(Settings({k: getattr(s, k) for k in dir(s) if k.isupper()}))


def test_retried_statuses_are_never_cached(monkeypatch):
    # The cache sits closer to the network than RetryMiddleware: a cached
    # error would be replayed to every retry, and the ship would never be fetched.
    from scrapy.http import Request, Response

    s = reloaded(monkeypatch)
    policy = _cache_policy(s)
    request = Request("https://threedecks.org/index.php?display_type=show_ship&id=1")
    cached = [
        code for code in s.RETRY_HTTP_CODES
        if policy.should_cache_response(Response(request.url, status=code), request)
    ]
    assert cached == []


def test_cloudflare_origin_errors_are_retried(monkeypatch):
    s = reloaded(monkeypatch)
    assert [code for code in CLOUDFLARE_ORIGIN_ERRORS if code not in s.RETRY_HTTP_CODES] == []


def test_sqlite_cache_and_no_jobdir(monkeypatch):
    s = reloaded(monkeypatch)
    assert s.HTTPCACHE_STORAGE == "threedecks.cache.SqliteCacheStorage"
    assert s.HTTPCACHE_EXPIRATION_SECS == 0
    assert s.TELNETCONSOLE_ENABLED is False
    assert s.REMOTE_CONTROL_ENABLED is False
    assert not hasattr(s, "JOBDIR")


def test_require_contact_rejects_the_placeholder():
    with pytest.raises(MissingContactError):
        require_contact(build_user_agent({}), {})
    ua = build_user_agent({"THREEDECKS_CONTACT": "owner@example.org"})
    assert require_contact(ua, {"THREEDECKS_CONTACT": "owner@example.org"}) == "owner@example.org"


def test_block_check_runs_before_retry_and_after_decompression(monkeypatch):
    # process_response runs from high to low priority: HttpCompression (590),
    # then the block check, then RetryMiddleware (550), which must never see a block.
    s = reloaded(monkeypatch)
    assert 550 < s.DOWNLOADER_MIDDLEWARES["threedecks.middlewares.BlockDetectionMiddleware"] < 590


def test_wba_signing_runs_after_the_http_cache(monkeypatch):
    # A cache replay short-circuits at HttpCacheMiddleware (900) and never
    # reaches the signer (950): only wire-bound requests are signed.
    s = reloaded(monkeypatch)
    assert s.DOWNLOADER_MIDDLEWARES["threedecks.wba.WebBotAuthMiddleware"] > 900


def test_spiders_own_the_depth_meta(monkeypatch):
    # DepthMiddleware would overwrite meta["depth"] and skip Tier B incarnations.
    s = reloaded(monkeypatch)
    assert s.SPIDER_MIDDLEWARES["scrapy.spidermiddlewares.depth.DepthMiddleware"] is None
    assert s.HTTPCACHE_POLICY == "threedecks.cache.ThreeDecksCachePolicy"


def test_cloudflare_cooloffs_are_long_and_few(monkeypatch):
    s = reloaded(monkeypatch)
    assert s.THREEDECKS_COOLOFF_SECS >= 10 * 60
    assert s.THREEDECKS_MAX_COOLOFFS <= 3


def test_requests_carry_the_contact_in_the_from_header(monkeypatch):
    s = reloaded(monkeypatch, contact="owner@example.org")
    assert s.DEFAULT_REQUEST_HEADERS["From"] == "owner@example.org"
    assert s.DEFAULT_REQUEST_HEADERS["Accept-Language"] == "en"
