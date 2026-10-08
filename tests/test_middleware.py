"""Layer 4-6: the block-detection middleware (Plan 4.2).

A 429 or a Cloudflare challenge is waited out with a long pause and retried
unchanged; a plain 403, or a block that outlasts the cool-offs, stops the
spider. Nothing is ever worked around (rule 5).
"""

from __future__ import annotations

import time

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import HtmlResponse, Request
from threedecks.middlewares import MAX_WAIT_SECS, BlockDetectionMiddleware

URL = "https://threedecks.org/index.php?display_type=show_ship&id=1"


class FakeEngine:
    def __init__(self):
        self.reasons: list[str] = []
        self.paused = False

    def close_spider_async(self, *, reason):
        self.reasons.append(reason)

    def pause(self):
        self.paused = True

    def unpause(self):
        self.paused = False


class FakeSpider:
    name = "test"

    def __init__(self):
        self.crawler = type("Crawler", (), {"engine": FakeEngine()})()


def response(status=200, body=b"<html>ok</html>", headers=None, url=URL):
    return HtmlResponse(url=url, status=status, body=body, headers=headers)


def middleware(max_cooloffs=3, clock=time.time):
    mw = BlockDetectionMiddleware(
        cooloff_secs=900, max_cooloffs=max_cooloffs,
        block_window_secs=7200, block_window_max=4, clock=clock,
    )
    mw.waits = []
    mw.call_later = lambda delay, func: mw.waits.append(delay)
    return mw


def assert_blocked(resp, mw=None, spider=None):
    # The response is dropped so RetryMiddleware never re-sends it.
    mw = mw or middleware(max_cooloffs=0)
    spider = spider or FakeSpider()
    with pytest.raises(IgnoreRequest):
        mw.process_response(Request(resp.url), resp, spider)
    assert spider.crawler.engine.reasons == ["blocked"]


def cool_off(mw, resp, spider):
    request = Request(resp.url, meta={"td_id": 1})
    result = mw.process_response(request, resp, spider)
    assert isinstance(result, Request)
    assert result.url == request.url and result.meta["td_id"] == 1
    assert spider.crawler.engine.paused
    spider.crawler.engine.unpause()
    return result


CHALLENGE = b"<html><title>Just a moment...</title><div class='cf-chl'></div></html>"


# --- stops ---------------------------------------------------------------------


def test_plain_403_closes_spider_without_waiting():
    mw = middleware()
    assert_blocked(response(403), mw)
    assert mw.waits == []


def test_429_closes_spider_when_cooloffs_are_off():
    assert_blocked(response(429))


def test_challenge_body_closes_spider_when_cooloffs_are_off():
    assert_blocked(response(200, CHALLENGE))


def test_503_challenge_is_detected():
    body = b"<script src='/cdn-cgi/challenge-platform/h/b/orchestrate/chl_page/v1'></script>"
    assert_blocked(response(503, body))


def test_cf_mitigated_header_is_detected():
    assert_blocked(response(200, headers={"cf-mitigated": "challenge"}))


def test_cf_mitigated_blocked_header_closes_without_a_cooloff():
    # A WAF block is a decision, not a challenge: cool-offs cannot lift it.
    mw = middleware()  # cool-offs available
    assert_blocked(response(200, headers={"cf-mitigated": "blocked"}), mw)
    assert mw.waits == []


def test_block_page_body_closes_without_a_cooloff():
    body = b"<html><title>Sorry, you have been blocked</title></html>"
    mw = middleware()
    assert_blocked(response(200, body), mw)
    assert mw.waits == []


def test_block_page_at_429_is_not_waited_out():
    mw = middleware()
    assert_blocked(response(429, headers={"cf-mitigated": "blocked"}), mw)
    assert mw.waits == []


def test_robots_txt_block_is_not_waited_out():
    # robots.txt is downloaded outside the scheduler, so pausing would not hold it.
    mw = middleware()
    assert_blocked(response(429, url="https://threedecks.org/robots.txt"), mw)
    assert mw.waits == []


def test_retry_after_beyond_the_cap_closes_spider():
    mw = middleware()
    headers = {"Retry-After": str(MAX_WAIT_SECS + 1)}
    assert_blocked(response(429, headers=headers), mw)


# --- cool-offs -----------------------------------------------------------------


def test_429_pauses_then_retries_the_same_request():
    mw, spider = middleware(), FakeSpider()
    cool_off(mw, response(429), spider)
    assert mw.waits == [900]
    assert spider.crawler.engine.reasons == []


def test_challenge_page_pauses_then_retries():
    mw, spider = middleware(), FakeSpider()
    cool_off(mw, response(403, CHALLENGE), spider)
    assert mw.waits == [900]


def test_retry_after_lengthens_the_wait():
    mw, spider = middleware(), FakeSpider()
    cool_off(mw, response(429, headers={"Retry-After": "3600"}), spider)
    assert mw.waits == [3600]


def test_cooloffs_double_then_the_spider_closes():
    mw, spider = middleware(), FakeSpider()
    for _ in range(3):
        cool_off(mw, response(429), spider)
    assert mw.waits == [900, 1800, 3600]
    assert_blocked(response(429), mw, spider)


def test_a_normal_response_resets_the_cooloffs():
    mw, spider = middleware(), FakeSpider()
    cool_off(mw, response(429), spider)
    mw.process_response(Request(URL), response(200), spider)
    cool_off(mw, response(429), spider)
    assert mw.waits == [900, 900]


# --- sliding-window escalation -------------------------------------------------


def test_blocks_with_200s_between_them_close_on_the_fourth():
    # The consecutive counter resets on every 200; the window still escalates.
    now = [0.0]
    mw, spider = middleware(clock=lambda: now[0]), FakeSpider()
    for _ in range(3):
        cool_off(mw, response(429), spider)
        mw.process_response(Request(URL), response(200), spider)
        now[0] += 60
    assert mw.waits == [900, 900, 900]
    assert_blocked(response(429), mw, spider)


def test_window_close_logs_the_count(caplog):
    import logging

    now = [0.0]
    mw, spider = middleware(clock=lambda: now[0]), FakeSpider()
    with caplog.at_level(logging.ERROR, logger="threedecks.middlewares"):
        for _ in range(3):
            cool_off(mw, response(429), spider)
            mw.process_response(Request(URL), response(200), spider)
            now[0] += 60
        assert_blocked(response(429), mw, spider)
    assert "4 blocks in 120 min" in caplog.text


def test_blocks_spread_beyond_the_window_keep_cooling_off():
    now = [0.0]
    mw, spider = middleware(clock=lambda: now[0]), FakeSpider()
    for _ in range(4):
        cool_off(mw, response(429), spider)
        mw.process_response(Request(URL), response(200), spider)
        now[0] += 3 * 3600  # longer than the 2 h window
    assert mw.waits == [900] * 4
    assert spider.crawler.engine.reasons == []


def test_normal_response_passes_through():
    spider = FakeSpider()
    result = middleware().process_response(Request(URL), response(200), spider)
    assert result.status == 200
    assert spider.crawler.engine.reasons == []


def test_cloudflare_bot_detection_script_is_not_a_challenge():
    # Cloudflare injects this script into ordinary pages; it must not close the crawl.
    body = (
        b"<html><table id='ship_base'></table><script>a.src="
        b"'/cdn-cgi/challenge-platform/scripts/jsd/main.js';</script></html>"
    )
    spider = FakeSpider()
    result = middleware().process_response(Request(URL), response(200, body), spider)
    assert result.status == 200
    assert spider.crawler.engine.reasons == []
