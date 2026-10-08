"""Layer 4: spider behaviour, offline against synthetic fixtures (Plan 6)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

import pytest
from scrapy.exceptions import IgnoreRequest
from scrapy.http import FormRequest, HtmlResponse, Request
from scrapy.spidermiddlewares.httperror import HttpError
from scrapy.utils.test import get_crawler
from threedecks.items import CaptureRow, ShipRecord
from threedecks.spiders.captures import CapturesSpider
from threedecks.spiders.ships_all import ShipsAllSpider
from threedecks.spiders.ships_by_nation import ShipsByNationSpider
from threedecks.state import StateStore
from threedecks.ua import MissingContactError, build_user_agent
from twisted.internet.error import TimeoutError
from twisted.python.failure import Failure

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def response_for(
    name, url="https://threedecks.org/index.php?display_type=x", status=200, meta=None
):
    body = (FIXTURES / name).read_bytes()
    request = Request(url, meta=meta or {})
    return HtmlResponse(url=url, body=body, encoding="utf-8", status=status, request=request)


def make(spider_cls, tmp_path, **kwargs):
    spider = spider_cls(
        name=spider_cls.name, base_url="http://local", data_dir=str(tmp_path), **kwargs
    )
    return spider


def make_with_crawler(spider_cls, monkeypatch, tmp_path):
    """Build the spider the way Scrapy does, so project settings and stats apply."""
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(spider_cls, {"USER_AGENT": build_user_agent()})
    spider = spider_cls.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
    return crawler, spider


# --- captures --------------------------------------------------------------


def test_captures_issues_one_form_post(tmp_path):
    spider = make(CapturesSpider, tmp_path)
    requests = list(spider.start_requests())
    spider.closed("test")
    assert len(requests) == 1
    assert isinstance(requests[0], FormRequest)
    assert requests[0].method == "POST"
    data = parse_qs(requests[0].body.decode())
    assert data["select_from_nation"] == ["7"]
    assert data["select_by_nation"] == ["1"]
    assert data["select_captures"] == ["Change Filter"]


def test_captures_parse_yields_rows_and_unique_ship_requests(tmp_path):
    spider = make(CapturesSpider, tmp_path)
    response = response_for("captures.html", "https://threedecks.org/index.php?display_type=select_capture")
    produced = list(spider.parse_captures(response))
    spider.closed("test")

    rows = [p for p in produced if isinstance(p, CaptureRow)]
    requests = [p for p in produced if isinstance(p, Request)]
    assert len(rows) == 4
    ids = [int(r.url.split("id=")[1]) for r in requests]
    assert sorted(ids) == [6420, 13716, 21635, 24577]


# --- incarnation following -------------------------------------------------


def test_incarnation_following_at_depth_zero(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    followed = sorted(int(r.url.split("id=")[1]) for r in requests)
    assert followed == [50, 60]


def test_incarnation_following_stops_at_max_depth(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 1},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    assert [p for p in produced if isinstance(p, Request)] == []


def test_captures_follows_incarnations_of_the_ships_it_names(monkeypatch, tmp_path):
    # Captured and captor ships are requested at depth 1; their Previously /
    # Becomes records must still be fetched, one hop further.
    _, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 1},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    assert sorted(int(r.url.split("id=")[1]) for r in requests) == [50, 60]
    assert {r.meta["depth"] for r in requests} == {2}


def test_captures_stops_after_one_incarnation_hop(monkeypatch, tmp_path):
    _, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 2},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    assert [p for p in produced if isinstance(p, Request)] == []


def test_sidebar_links_are_not_followed(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    followed = {int(r.url.split("id=")[1]) for r in produced if isinstance(r, Request)}
    assert 9999 not in followed and 7777 not in followed and 8888 not in followed


# --- search pagination -----------------------------------------------------


def test_search_pagination_requests_next_page(tmp_path):
    spider = make(ShipsByNationSpider, tmp_path)
    produced = list(spider.parse_search(response_for("search_page1.html")))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    ship_ids = sorted(int(r.url.split("id=")[1]) for r in requests if "show_ship" in r.url)
    next_pages = [r for r in requests if "ships_search" in r.url]
    assert ship_ids == [16801, 16802, 16803]
    assert len(next_pages) == 1
    assert parse_qs(next_pages[0].body.decode())["page"] == ["2"]


def test_search_last_page_stops(tmp_path):
    spider = make(ShipsByNationSpider, tmp_path)
    produced = list(spider.parse_search(response_for("search_page2.html")))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    assert [r for r in requests if "ships_search" in r.url] == []
    assert sorted(int(r.url.split("id=")[1]) for r in requests) == [17000]


# --- seeding ---------------------------------------------------------------


SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=10</loc></url>
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=12</loc></url>
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=14</loc></url>
</urlset>
"""


def test_sitemap_seeding_is_idempotent(tmp_path):
    spider = make(ShipsAllSpider, tmp_path)
    response = HtmlResponse(url="https://threedecks.org/ships.xml", body=SITEMAP, encoding="utf-8")

    first = list(spider.parse_sitemap(response))
    first_ids = sorted(int(r.url.split("id=")[1]) for r in first if isinstance(r, Request))
    # 10, 12, 14 from the sitemap, gaps 1..9/11/13, then the upward probe at 15.
    assert set(first_ids) == set(range(1, 15)) | {15}
    assert spider.store.counts_by_status() == {"pending": 15}

    list(spider.parse_sitemap(response))
    counts = spider.store.counts_by_status()
    spider.closed("test")
    # The second pass re-seeds nothing; only the upward probe advances (16).
    assert counts == {"pending": 16}


def test_sitemap_gaps_reach_ids_found_by_earlier_tiers(tmp_path):
    # Tier A found ship 40, far above the stale sitemap's maximum (14); ids 15-39
    # must still be tried, and the upward scan starts above 40.
    spider = make(ShipsAllSpider, tmp_path)
    spider.store.seed([40], discovered_by="captures", depth=1)
    spider.store.mark_status(40, "done")
    response = HtmlResponse(url="https://threedecks.org/ships.xml", body=SITEMAP, encoding="utf-8")

    ids = [int(r.url.split("id=")[1]) for r in spider.parse_sitemap(response)]
    spider.closed("test")
    assert sorted(ids) == list(range(1, 40)) + [41]


def test_trailing_not_found_counts_streak(tmp_path):
    from threedecks.state import StateStore

    store = StateStore(tmp_path / "state.sqlite")
    store.seed([1, 2, 3, 4], discovered_by="test")
    store.mark_status(2, "not_found")
    store.mark_status(3, "not_found")
    store.mark_status(4, "not_found")
    assert store.trailing_not_found() == 3
    store.mark_status(4, "done")
    assert store.trailing_not_found() == 0
    store.close()


# --- identifiable User-Agent (rule 2) and crawl stats ----------------------


def test_spider_refuses_to_start_without_a_contact(monkeypatch, tmp_path):
    monkeypatch.delenv("THREEDECKS_CONTACT", raising=False)
    crawler = get_crawler(CapturesSpider, {"USER_AGENT": build_user_agent()})
    with pytest.raises(MissingContactError):
        CapturesSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))


def test_spider_refuses_a_user_agent_without_the_contact(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(ShipsAllSpider, {"USER_AGENT": "something-else/1.0"})
    with pytest.raises(MissingContactError):
        ShipsAllSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))


def test_unknown_labels_and_sections_are_counted_in_stats(monkeypatch, tmp_path):
    crawler, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    list(spider.parse_ship_page(response))
    spider.closed("test")
    assert crawler.stats.get_value("threedecks/unknown_label/Refloated By") == 1
    assert not any(
        key.startswith("threedecks/unknown_section/") for key in crawler.stats.get_stats()
    )


# --- failed fetches and parser exceptions (Plan 4.3, step 7) -----------------


def failure_for(exc, request):
    failure = Failure(exc)
    failure.request = request
    return failure


def frontier_row(spider, td_id):
    return dict(
        spider.store._conn.execute(  # noqa: SLF001
            "SELECT status, attempts, http_status FROM frontier WHERE td_id = ?", (td_id,)
        ).fetchone()
    )


def test_failed_fetch_marks_error_and_counts_an_attempt(monkeypatch, tmp_path):
    crawler, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    request = spider.ship_request(42, depth=1)
    assert request.errback == spider.on_ship_error
    not_found = HtmlResponse(url=request.url, status=404, body=b"", request=request)

    spider.on_ship_error(failure_for(HttpError(not_found), request))
    assert frontier_row(spider, 42) == {"status": "error", "attempts": 1, "http_status": 404}

    spider.on_ship_error(failure_for(TimeoutError(), request))
    assert frontier_row(spider, 42) == {"status": "error", "attempts": 2, "http_status": None}
    assert crawler.stats.get_value("threedecks/fetch_error") == 2
    spider.closed("test")


def test_blocked_fetch_leaves_the_row_pending(monkeypatch, tmp_path):
    _, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    spider.store.seed([42], discovered_by="test")
    request = spider.ship_request(42)
    spider.on_ship_error(failure_for(IgnoreRequest("blocked"), request))
    assert frontier_row(spider, 42)["status"] == "pending"
    assert frontier_row(spider, 42)["attempts"] == 0
    spider.closed("test")


def test_parser_exception_marks_parse_error_and_moves_on(monkeypatch, tmp_path):
    def broken(*args, **kwargs):
        raise ValueError("new markup")

    monkeypatch.setattr("threedecks.spiders.base.parse_ship", broken)
    crawler, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    assert list(spider.parse_ship_page(response)) == []
    assert spider.store.status(1234) == "parse_error"
    assert crawler.stats.get_value("threedecks/parse_error") == 1
    spider.closed("test")


def test_captures_list_replaces_the_rows_of_its_query(tmp_path):
    # Keys changed format in parser 2; a re-parse must not leave the old rows behind.
    spider = make(CapturesSpider, tmp_path)
    with spider.store._conn:  # noqa: SLF001
        spider.store._conn.execute(  # noqa: SLF001
            "INSERT INTO captures VALUES ('7|1|None|13269|1804/12/07', '{}')"
        )
    list(spider.parse_captures(response_for("captures.html")))
    assert spider.store.capture_count() == 0  # the pipeline re-saves the new rows
    spider.closed("test")


# --- overnight-run fixes -----------------------------------------------------

SHIP_URL = "https://threedecks.org/index.php?display_type=show_ship&id=1234"


def test_a_page_replayed_from_the_cache_keeps_its_fetch_time(tmp_path):
    spider = make(ShipsAllSpider, tmp_path)
    response = response_for(
        "ship_full.html", SHIP_URL, meta={"depth": 0, "cache_timestamp": 1_790_000_000.0}
    )
    record = next(p for p in spider.parse_ship_page(response) if isinstance(p, ShipRecord))
    spider.closed("test")
    assert record.fetched_at == "2026-09-21T14:13:20Z"  # not the time of the replay


def test_an_id_is_requested_once_per_run_at_its_shallowest_depth(tmp_path):
    spider = make(CapturesSpider, tmp_path)
    ids = lambda requests: [(r.meta["td_id"], r.meta["depth"]) for r in requests]  # noqa: E731
    assert ids(spider.ship_requests([5, 6, 5], depth=2, discovered_by="x")) == [(5, 2), (6, 2)]
    assert ids(spider.ship_requests([5, 7], depth=2, discovered_by="x")) == [(7, 2)]
    # Seen again on a list (depth 1): fetched again so its own links are followed.
    assert ids(spider.ship_requests([5], depth=1, discovered_by="x")) == [(5, 1)]
    assert ids(spider.ship_requests([5], depth=2, discovered_by="x")) == []
    spider.closed("test")


def test_a_network_outage_closes_without_charging_attempts(monkeypatch, tmp_path):
    _, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    for td_id in (1, 2):
        spider.on_ship_error(failure_for(TimeoutError(), spider.ship_request(td_id)))
    assert frontier_row(spider, 1)["attempts"] == 1  # a one-off timeout still counts
    assert closed == []

    spider.on_ship_error(failure_for(TimeoutError(), spider.ship_request(3)))
    assert closed == ["network_down"]
    released = {"status": "pending", "attempts": 0, "http_status": None}
    for td_id in (1, 2, 3):
        assert frontier_row(spider, td_id) == released
    spider.on_ship_error(failure_for(TimeoutError(), spider.ship_request(4)))  # was in flight
    assert frontier_row(spider, 4)["attempts"] == 0
    spider.closed("test")


def test_a_response_resets_the_network_streak(monkeypatch, tmp_path):
    _, spider = make_with_crawler(CapturesSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    for td_id in (1, 2):
        spider.on_ship_error(failure_for(TimeoutError(), spider.ship_request(td_id)))
    list(spider.parse_ship_page(response_for("ship_full.html", SHIP_URL, meta={"depth": 9})))
    spider.on_ship_error(failure_for(TimeoutError(), spider.ship_request(3)))
    assert closed == []
    assert frontier_row(spider, 3)["attempts"] == 1
    spider.closed("test")


def test_the_run_log_counts_pages_fetched_from_the_site(monkeypatch, tmp_path):
    crawler, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    spider.on_opened()
    crawler.stats.set_value("response_received_count", 10)
    crawler.stats.set_value("httpcache/hit", 4)
    run_id = spider._run_id
    spider.closed("finished")
    store = StateStore(tmp_path / "state.sqlite")
    assert store.get_run(run_id)["pages_fetched"] == 6
    store.close()


# --- the incomplete-page streak breaker (anti-bot hardening, phase E) --------


INCOMPLETE_PAGE = (
    b"<!DOCTYPE html><html><head><title>Ship</title></head><body>"
    b"<div id='datacol'><table id='ship_base'><tbody>"
    b"<tr><td>Nominal Guns</td><td>74</td></tr></tbody></table></div>"
    b"</body></html>"  # the footer after #datacol is missing: a truncated page
)


def incomplete_response(td_id, meta=None):
    url = f"https://threedecks.org/index.php?display_type=show_ship&id={td_id}"
    request = Request(url, meta=meta if meta is not None else {"depth": 0, "td_id": td_id})
    return HtmlResponse(url=url, body=INCOMPLETE_PAGE, encoding="utf-8", request=request)


def test_a_streak_of_incomplete_pages_closes_the_crawl(monkeypatch, tmp_path):
    _, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    spider.store.seed([1, 2, 3], discovered_by="test")
    for td_id in (1, 2):
        assert list(spider.parse_ship_page(incomplete_response(td_id)))  # error + one retry
    assert list(spider.parse_ship_page(incomplete_response(3))) == []  # no retry on close
    assert closed == ["incomplete_streak"]
    for td_id in (1, 2, 3):  # the streak's attempts are not counted
        assert frontier_row(spider, td_id)["status"] == "pending"
    spider.closed("test")


def test_one_incomplete_page_does_not_close_the_crawl(monkeypatch, tmp_path):
    _, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    produced = list(spider.parse_ship_page(incomplete_response(1)))
    retries = [p for p in produced if isinstance(p, Request)]
    assert closed == []
    assert len(retries) == 1 and retries[0].meta["completeness_retries"] == 1
    assert frontier_row(spider, 1)["status"] == "error"
    spider.closed("test")


def test_a_pages_own_retry_does_not_double_count(monkeypatch, tmp_path):
    _, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    list(spider.parse_ship_page(incomplete_response(1)))
    list(spider.parse_ship_page(
        incomplete_response(1, meta={"depth": 0, "td_id": 1, "completeness_retries": 1})
    ))
    assert spider._incomplete_streak == [1]  # noqa: SLF001
    assert closed == []
    spider.closed("test")


def test_a_complete_page_clears_the_incomplete_streak(monkeypatch, tmp_path):
    _, spider = make_with_crawler(ShipsAllSpider, monkeypatch, tmp_path)
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    for td_id in (1, 2):
        list(spider.parse_ship_page(incomplete_response(td_id)))
    assert spider._incomplete_streak == [1, 2]  # noqa: SLF001
    list(spider.parse_ship_page(response_for("ship_full.html", SHIP_URL, meta={"depth": 0})))
    assert spider._incomplete_streak == []  # noqa: SLF001
    list(spider.parse_ship_page(incomplete_response(3)))
    assert closed == []
    spider.closed("test")


def test_incomplete_limit_zero_disables_the_breaker(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(
        ShipsAllSpider, {"USER_AGENT": build_user_agent(), "THREEDECKS_INCOMPLETE_LIMIT": 0}
    )
    spider = ShipsAllSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
    closed = []
    monkeypatch.setattr(spider, "_close", closed.append)
    for td_id in (1, 2, 3, 4):
        list(spider.parse_ship_page(incomplete_response(td_id)))
    assert closed == []
    spider.closed("test")
