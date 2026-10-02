"""Layer 6: the politeness contract (Plan 4.2, 6).

Loosening any of these must be a deliberate, visible change. Scrapy contracts
(`scrapy check`) are not used because they make live requests.
"""

from __future__ import annotations

import importlib

import threedecks.settings as settings


def reloaded(monkeypatch, contact="contact@example.org"):
    monkeypatch.setenv("THREEDECKS_CONTACT", contact)
    return importlib.reload(settings)


def test_delay_is_at_least_the_robots_crawl_delay(monkeypatch):
    s = reloaded(monkeypatch)
    assert s.DOWNLOAD_DELAY >= 5
    assert s.RANDOMIZE_DOWNLOAD_DELAY is False
    assert s.AUTOTHROTTLE_START_DELAY >= 5


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


def test_sqlite_cache_and_no_jobdir(monkeypatch):
    s = reloaded(monkeypatch)
    assert s.HTTPCACHE_STORAGE == "threedecks.cache.SqliteCacheStorage"
    assert s.HTTPCACHE_EXPIRATION_SECS == 0
    assert not hasattr(s, "JOBDIR")
