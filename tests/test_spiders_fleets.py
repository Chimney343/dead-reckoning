"""The ``fleets`` spider (Task FL6), offline against synthetic fixtures."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from scrapy.http import HtmlResponse, Request
from scrapy.utils.test import get_crawler
from threedecks.items import FleetRow, ShipRecord
from threedecks.spiders.fleets import FleetsSpider
from threedecks.ua import build_user_agent

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def make(spider_cls=FleetsSpider, tmp_path=None):
    return spider_cls(name=spider_cls.name, base_url="http://local", data_dir=str(tmp_path))


def make_with_crawler(monkeypatch, tmp_path):
    monkeypatch.setenv("THREEDECKS_CONTACT", "owner@example.org")
    crawler = get_crawler(FleetsSpider, {"USER_AGENT": build_user_agent()})
    spider = FleetsSpider.from_crawler(crawler, base_url="http://local", data_dir=str(tmp_path))
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


def test_empty_store_yields_one_index_get(tmp_path):
    spider = make(tmp_path=tmp_path)
    requests = requests_of(list(spider.start_requests()))
    assert len(requests) == 1
    assert requests[0].method == "GET"
    assert display_types(requests) == {"show_fleetlist"}
    spider.closed("test")


def test_ship_record_seeding_requests_the_cited_fleet(tmp_path):
    spider = make(tmp_path=tmp_path)
    spider.store.save_ship(
        ShipRecord(td_id=2682, name="San Ildefonso", fleets=[FleetRow(fleet_id=139)])
    )
    requests = requests_of(list(spider.start_requests()))
    assert display_types([requests[0]]) == {"show_fleetlist"}  # the index goes first
    fleet_requests = [r for r in requests if "show_fleet&id=" in r.url]
    assert [parse_qs(urlparse(r.url).query)["id"][0] for r in fleet_requests] == ["139"]
    assert all(r.meta["kind"] == "fleet" for r in fleet_requests)
    spider.closed("test")


# --- the index callback -----------------------------------------------------


def test_parse_index_stores_rows_and_seeds_fleets(tmp_path):
    spider = make(tmp_path=tmp_path)
    response = response_for(
        "fleetlist_index.html",
        "http://local/index.php?display_type=show_fleetlist",
        {"kind": "fleet_index", "key": "1"},
    )
    requests = requests_of(list(spider.parse_index(response)))

    assert spider.store.page_status("fleet_index", "1") == "done"
    assert [row["fleet_id"] for row in spider.store.iter_fleet_index()] == [69, 132, 139]
    assert spider.store.page_status("fleet", "132") == "pending"
    assert spider.store.page_status("fleet", "69") == "pending"
    assert spider.store.page_status("fleet", "139") == "pending"

    assert sorted(int(parse_qs(urlparse(r.url).query)["id"][0]) for r in requests) == [
        69,
        132,
        139,
    ]
    spider.closed("test")


def test_parse_index_second_call_yields_nothing(tmp_path):
    spider = make(tmp_path=tmp_path)
    response = response_for(
        "fleetlist_index.html",
        "http://local/index.php?display_type=show_fleetlist",
        {"kind": "fleet_index", "key": "1"},
    )
    list(spider.parse_index(response))
    assert requests_of(list(spider.parse_index(response))) == []
    spider.closed("test")


def test_a_done_index_yields_only_pending_fleets(tmp_path):
    spider = make(tmp_path=tmp_path)
    spider.store.seed_pages("fleet_index", ["1"], discovered_by="start")
    spider.store.save_fleet_index([])  # marks the index done
    spider.store.seed_pages("fleet", ["139"], discovered_by="ship_fleets")
    requests = requests_of(list(spider.start_requests()))
    assert display_types(requests) == {"show_fleet"}
    assert parse_qs(urlparse(requests[0].url).query)["id"] == ["139"]
    spider.closed("test")


# --- fleet pages and the not-found shell ------------------------------------


def test_fleet_not_found_is_recorded(tmp_path):
    spider = make(tmp_path=tmp_path)
    response = response_for(
        "fleet_notfound.html",
        "http://local/index.php?display_type=show_fleet&id=999999",
        {"kind": "fleet", "key": "999999", "depth": 0},
    )
    assert list(spider.parse_entity_page(response)) == []
    assert spider.store.page_status("fleet", "999999") == "not_found"
    spider.closed("test")


def test_truncated_fleet_marks_error_and_retries_once(monkeypatch, tmp_path):
    crawler, spider = make_with_crawler(monkeypatch, tmp_path)
    response = response_for(
        "fleet_truncated.html",
        "http://local/index.php?display_type=show_fleet&id=5",
        {"kind": "fleet", "key": "5", "depth": 0},
    )
    retries = requests_of(list(spider.parse_entity_page(response)))
    assert len(retries) == 1
    assert retries[0].meta["completeness_retries"] == 1
    assert spider.store.page_status("fleet", "5") == "error"
    assert crawler.stats.get_value("threedecks/fleet/incomplete_page") == 1
    spider.closed("test")


def test_a_parsed_fleet_page_yields_a_record(monkeypatch, tmp_path):
    _, spider = make_with_crawler(monkeypatch, tmp_path)
    response = response_for(
        "fleet_full.html",
        "http://local/index.php?display_type=show_fleet&id=555",
        {"kind": "fleet", "key": "555", "depth": 0},
    )
    records = [item for item in spider.parse_entity_page(response) if not isinstance(item, Request)]
    assert len(records) == 1
    assert records[0].fleet_id == 555
    spider.closed("test")


# --- separation (only two page types, ever) ---------------------------------


def test_only_index_and_fleet_pages_are_requested(monkeypatch, tmp_path):
    _, spider = make_with_crawler(monkeypatch, tmp_path)
    collected = list(spider.start_requests())
    collected += list(
        spider.parse_index(
            response_for(
                "fleetlist_index.html",
                "http://local/index.php?display_type=show_fleetlist",
                {"kind": "fleet_index", "key": "1"},
            )
        )
    )
    for name, url, meta in (
        ("fleet_full.html", "http://local/index.php?display_type=show_fleet&id=555", "555"),
        ("fleet_notfound.html", "http://local/index.php?display_type=show_fleet&id=999999",
         "999999"),
    ):
        collected += list(
            spider.parse_entity_page(
                response_for(name, url, {"kind": "fleet", "key": meta, "depth": 0})
            )
        )
    spider.closed("test")
    # fleet_full.html links a battle in an event; it must never be requested.
    assert display_types(requests_of(collected)) <= {"show_fleetlist", "show_fleet"}


def test_fleets_spider_defines_no_custom_settings():
    assert "custom_settings" not in FleetsSpider.__dict__
