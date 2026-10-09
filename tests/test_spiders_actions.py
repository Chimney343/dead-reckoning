"""The ``actions`` spider (Task A6), offline against synthetic fixtures."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from scrapy.exceptions import CloseSpider
from scrapy.http import HtmlResponse, Request
from scrapy.utils.test import get_crawler
from threedecks.forms import action_index_form
from threedecks.items import HistoryEvent, ShipRecord
from threedecks.settings import TARGETED_CLOSE_REASON
from threedecks.spiders.actions import ActionsSpider
from threedecks.ua import build_user_agent

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def make(spider_cls=ActionsSpider, tmp_path=None):
    return spider_cls(name=spider_cls.name, base_url="http://local", data_dir=str(tmp_path))


def make_with_crawler(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(ActionsSpider, {"USER_AGENT": build_user_agent()})
    spider = ActionsSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
    return crawler, spider


def response_for(name, url, meta):
    body = (FIXTURES / name).read_bytes()
    request = Request(url, meta=meta)
    return HtmlResponse(url=url, body=body, encoding="utf-8", request=request)


def requests_of(produced):
    return [item for item in produced if isinstance(item, Request)]


def display_types(requests):
    return {
        parse_qs(urlparse(request.url).query)["display_type"][0] for request in requests
    }


# --- seeding and start ------------------------------------------------------


def test_empty_store_yields_one_index_post(tmp_path):
    spider = make(tmp_path=tmp_path)
    produced = list(spider.start_requests())
    requests = requests_of(produced)
    assert len(requests) == 1
    assert requests[0].method == "POST"
    assert parse_qs(requests[0].body.decode(), keep_blank_values=True) == {
        key: [value] for key, value in action_index_form(1).items()
    }
    spider.closed("test")


def test_history_seeding_requests_the_cited_battles(tmp_path):
    spider = make(tmp_path=tmp_path)
    spider.store.save_ship(
        ShipRecord(
            td_id=2682,
            name="San Ildefonso",
            history=[HistoryEvent(text="a", battle_ids=[149, 157])],
        )
    )
    produced = list(spider.start_requests())
    requests = requests_of(produced)
    assert requests[0].method == "POST"  # the index goes first
    ids = sorted(int(parse_qs(urlparse(r.url).query)["id"][0]) for r in requests[1:])
    assert ids == [149, 157]
    assert all(r.meta["kind"] == "action" for r in requests[1:])
    spider.closed("test")


def test_targeted_action_ids_fetch_only_those_pages(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(
        ActionsSpider,
        {"USER_AGENT": build_user_agent(), "THREEDECKS_ACTION_IDS": "343, 24, not-an-id"},
    )
    spider = ActionsSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
    requests = requests_of(list(spider.start_requests()))
    assert display_types(requests) == {"show_battle"}  # no index POST
    assert sorted(int(parse_qs(urlparse(r.url).query)["id"][0]) for r in requests) == [24, 343]
    assert spider.store.page_status("action", "343") == "pending"
    spider.closed("test")


def test_targeted_run_does_not_mark_the_tier_finished(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(
        ActionsSpider,
        {"USER_AGENT": build_user_agent(), "THREEDECKS_ACTION_IDS": "343"},
    )
    spider = ActionsSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
    with pytest.raises(CloseSpider) as exc:
        spider._close_targeted()
    assert exc.value.reason == TARGETED_CLOSE_REASON
    assert TARGETED_CLOSE_REASON != "finished"  # or a later crawl would skip the tier
    spider.closed("test")


# --- the index callback -----------------------------------------------------


def test_parse_index_stores_rows_seeds_pages_and_actions(tmp_path):
    spider = make(tmp_path=tmp_path)
    response = response_for(
        "action_index.html",
        "http://local/index.php?display_type=select_action",
        {"kind": "action_index", "key": "1"},
    )
    produced = list(spider.parse_index(response))
    requests = requests_of(produced)

    assert spider.store.page_status("action_index", "1") == "done"
    assert spider.store.page_status("action_index", "2") == "pending"
    assert spider.store.page_status("action", "1145") == "pending"
    assert spider.store.page_status("action", "938") == "pending"

    index_requests = [r for r in requests if "select_action" in r.url]
    action_requests = [r for r in requests if "show_battle" in r.url]
    assert len(index_requests) == 1
    assert parse_qs(index_requests[0].body.decode())["page"] == ["2"]
    assert sorted(int(parse_qs(urlparse(r.url).query)["id"][0]) for r in action_requests) == [
        938,
        1145,
    ]
    spider.closed("test")


def test_parse_index_second_call_yields_nothing(tmp_path):
    spider = make(tmp_path=tmp_path)
    response = response_for(
        "action_index.html",
        "http://local/index.php?display_type=select_action",
        {"kind": "action_index", "key": "1"},
    )
    list(spider.parse_index(response))
    again = list(spider.parse_index(response))
    assert requests_of(again) == []
    spider.closed("test")


# --- action pages and the not-found redirect --------------------------------


def test_redirected_not_found_is_recorded_and_not_parsed_as_index(monkeypatch, tmp_path):
    _, spider = make_with_crawler(monkeypatch, tmp_path)
    response = response_for(
        "action_notfound.html",
        "http://local/index.php?display_type=select_action",
        {"kind": "action", "key": "999999"},
    )
    assert list(spider.parse_entity_page(response)) == []
    assert spider.store.page_status("action", "999999") == "not_found"
    assert spider.store.page_status("action_index", "1") is None
    spider.closed("test")


def test_truncated_action_marks_error_and_retries_once(monkeypatch, tmp_path):
    crawler, spider = make_with_crawler(monkeypatch, tmp_path)
    response = response_for(
        "action_truncated.html",
        "http://local/index.php?display_type=show_battle&id=5",
        {"kind": "action", "key": "5", "depth": 0},
    )
    produced = list(spider.parse_entity_page(response))
    retries = requests_of(produced)
    assert len(retries) == 1
    assert retries[0].meta["completeness_retries"] == 1
    assert spider.store.page_status("action", "5") == "error"
    assert crawler.stats.get_value("threedecks/action/incomplete_page") == 1
    spider.closed("test")


def test_a_parsed_action_page_yields_a_record(monkeypatch, tmp_path):
    _, spider = make_with_crawler(monkeypatch, tmp_path)
    response = response_for(
        "action_minimal.html",
        "http://local/index.php?display_type=show_battle&id=42",
        {"kind": "action", "key": "42", "depth": 0},
    )
    produced = list(spider.parse_entity_page(response))
    records = [item for item in produced if not isinstance(item, Request)]
    assert len(records) == 1
    assert records[0].battle_id == 42
    spider.closed("test")


# --- separation (only two page types, ever) ---------------------------------


def test_only_index_and_action_pages_are_requested(monkeypatch, tmp_path):
    _, spider = make_with_crawler(monkeypatch, tmp_path)
    collected = list(spider.start_requests())
    collected += list(
        spider.parse_index(
            response_for(
                "action_index.html",
                "http://local/index.php?display_type=select_action",
                {"kind": "action_index", "key": "1"},
            )
        )
    )
    collected += list(
        spider.parse_entity_page(
            response_for(
                "action_full.html",
                "http://local/index.php?display_type=show_battle&id=555",
                {"kind": "action", "key": "555", "depth": 0},
            )
        )
    )
    collected += list(
        spider.parse_entity_page(
            response_for(
                "action_notfound.html",
                "http://local/index.php?display_type=select_action",
                {"kind": "action", "key": "999999"},
            )
        )
    )
    spider.closed("test")
    assert display_types(requests_of(collected)) <= {"select_action", "show_battle"}


def test_actions_spider_defines_no_custom_settings():
    assert "custom_settings" not in ActionsSpider.__dict__
