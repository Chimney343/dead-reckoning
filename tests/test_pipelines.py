"""Layer 4-6: validation and the state pipeline (Plan 4, 4.3 step 3)."""

from __future__ import annotations

import pytest
from scrapy.exceptions import DropItem, NotConfigured
from scrapy.http import HtmlResponse, Request
from scrapy.settings import Settings
from scrapy.utils.test import get_crawler
from threedecks.items import ActionRecord, CaptureRow, FleetRecord, ShipRecord
from threedecks.parsing.dates import parse_td_date
from threedecks.pipelines import StatePipeline, ValidationPipeline
from threedecks.state import StateStore


class FakeSettings(Settings):
    pass


def make_crawler(tmp_path):
    settings = Settings()
    settings.set("DATA_DIR", str(tmp_path), priority="default")
    return type("Crawler", (), {"settings": settings})()


class FakeSpider:
    name = "test"


def test_validation_rejects_ship_without_id():
    with pytest.raises(DropItem):
        ValidationPipeline().process_item(ShipRecord(td_id=None, name="x"), FakeSpider())


def test_validation_rejects_nameless_ship():
    with pytest.raises(DropItem):
        ValidationPipeline().process_item(ShipRecord(td_id=1, name=""), FakeSpider())


def test_validation_passes_valid_items():
    pipeline = ValidationPipeline()
    ship = ShipRecord(td_id=1, name="x")
    assert pipeline.process_item(ship, FakeSpider()) is ship
    row = CaptureRow(captured_td_id=2, captured_label="y", date=parse_td_date("1704/04/16"))
    assert pipeline.process_item(row, FakeSpider()) is row


def test_validation_rejects_action_without_id_or_name():
    pipeline = ValidationPipeline()
    with pytest.raises(DropItem):
        pipeline.process_item(ActionRecord(battle_id=None, name="x"), FakeSpider())
    with pytest.raises(DropItem):
        pipeline.process_item(ActionRecord(battle_id=1, name=""), FakeSpider())
    valid = ActionRecord(battle_id=1, name="Battle")
    assert pipeline.process_item(valid, FakeSpider()) is valid


def test_action_kind_is_registered():
    import threedecks.kinds_actions  # noqa: F401  (registers on import)
    from threedecks.pages import KINDS

    assert KINDS["action"].display_type == "show_battle"
    assert KINDS["action"].parser_version == "1"


def test_validation_rejects_fleet_without_id_or_name():
    pipeline = ValidationPipeline()
    with pytest.raises(DropItem):
        pipeline.process_item(FleetRecord(fleet_id=None, name="x"), FakeSpider())
    with pytest.raises(DropItem):
        pipeline.process_item(FleetRecord(fleet_id=1, name=""), FakeSpider())
    valid = FleetRecord(fleet_id=1, name="A Fleet")
    assert pipeline.process_item(valid, FakeSpider()) is valid


def test_fleet_kind_is_registered():
    import threedecks.kinds_fleets  # noqa: F401  (registers on import)
    from threedecks.pages import KINDS

    assert KINDS["fleet"].display_type == "show_fleet"
    assert KINDS["fleet"].parser_version == "1"


def test_state_pipeline_upserts_and_marks_done(tmp_path):
    pipeline = StatePipeline.from_crawler(make_crawler(tmp_path))
    spider = FakeSpider()
    pipeline.open_spider(spider)
    try:
        pipeline.process_item(ShipRecord(td_id=42, name="Answer"), spider)
    finally:
        pipeline.close_spider(spider)

    store = StateStore(tmp_path / "state.sqlite")
    assert store.status(42) == "done"
    assert store.get_ship(42)["name"] == "Answer"
    store.close()


def test_state_pipeline_saves_captures(tmp_path):
    pipeline = StatePipeline.from_crawler(make_crawler(tmp_path))
    spider = FakeSpider()
    pipeline.open_spider(spider)
    try:
        pipeline.process_item(
            CaptureRow(captured_td_id=2, captured_label="y", date=parse_td_date("1704/04/16")),
            spider,
        )
    finally:
        pipeline.close_spider(spider)

    store = StateStore(tmp_path / "state.sqlite")
    assert store.capture_count() == 1
    store.close()


def test_state_pipeline_saves_actions(tmp_path):
    pipeline = StatePipeline.from_crawler(make_crawler(tmp_path))
    spider = FakeSpider()
    pipeline.open_spider(spider)
    try:
        pipeline.process_item(ActionRecord(battle_id=157, name="Battle of Trafalgar"), spider)
    finally:
        pipeline.close_spider(spider)

    store = StateStore(tmp_path / "state.sqlite")
    assert store.action_count() == 1
    assert store.page_status("action", "157") == "done"
    store.close()


def test_state_pipeline_saves_fleets(tmp_path):
    pipeline = StatePipeline.from_crawler(make_crawler(tmp_path))
    spider = FakeSpider()
    pipeline.open_spider(spider)
    try:
        pipeline.process_item(FleetRecord(fleet_id=97, name="Saumarez's Squadron 1798"), spider)
    finally:
        pipeline.close_spider(spider)

    store = StateStore(tmp_path / "state.sqlite")
    assert store.fleet_count() == 1
    assert store.page_status("fleet", "97") == "done"
    store.close()


def test_heartbeat_reports_progress_and_cooloffs(tmp_path):
    import json

    from scrapy.utils.test import get_crawler
    from threedecks.extensions import HEARTBEAT_FILE, Heartbeat

    crawler = get_crawler(
        settings_dict={"DATA_DIR": str(tmp_path), "THREEDECKS_RUN_TOKEN": "abc"}
    )
    beat = Heartbeat.from_crawler(crawler)
    crawler.stats.set_value("response_received_count", 12)
    crawler.stats.set_value("threedecks/cooloff_until", 1234.5)
    beat.beat()
    data = json.loads((tmp_path / HEARTBEAT_FILE).read_text(encoding="utf-8"))
    assert data["responses"] == 12
    assert data["cooloff_until"] == 1234.5
    assert data["closed"] is None
    assert data["token"] == "abc"  # how the watchdog recognises this crawl


def test_heartbeat_logs_the_rate_at_the_site_apart_from_the_cache(tmp_path, caplog):
    import logging

    from scrapy.utils.test import get_crawler
    from threedecks.extensions import Heartbeat

    crawler = get_crawler(settings_dict={"DATA_DIR": str(tmp_path)})
    beat = Heartbeat.from_crawler(crawler)
    beat.log_interval = 0
    beat.beat()
    crawler.stats.set_value("response_received_count", 120)
    crawler.stats.set_value("httpcache/hit", 112)
    with caplog.at_level(logging.INFO, logger="threedecks.extensions"):
        beat.beat()
    assert "pages from the site: 8 " in caplog.text
    assert "from the cache: 112" in caplog.text


# --- the daily budget / crawl window extension (anti-bot hardening, phase D) --


class FakeEngine:
    def __init__(self):
        self.reasons: list[str] = []

    def close_spider_async(self, *, reason):
        self.reasons.append(reason)


def budget_extension(daily_pages=0, stop_at=0.0):
    from threedecks.extensions import CrawlBudget

    crawler = type("Crawler", (), {"engine": FakeEngine()})()
    return CrawlBudget(crawler, daily_pages, stop_at), crawler


URL = "https://threedecks.org/index.php?display_type=show_ship&id=1"


def live_response(url=URL):
    return HtmlResponse(
        url=url, body=b"<html>ok</html>", encoding="utf-8", request=Request(url)
    )


def test_crawl_budget_is_off_unless_configured():
    from threedecks.extensions import CrawlBudget

    with pytest.raises(NotConfigured):
        CrawlBudget.from_crawler(get_crawler())
    crawler = get_crawler(settings_dict={"THREEDECKS_DAILY_PAGES": 7})
    extension = CrawlBudget.from_crawler(crawler)
    assert extension.daily_pages == 7
    assert extension.stop_at == 0.0


def test_crawl_budget_counts_live_pages_and_closes_once():
    extension, crawler = budget_extension(daily_pages=2)
    for _ in range(2):
        extension.response_received(live_response(), Request(URL), FakeSpider())
    assert crawler.engine.reasons == ["daily_budget"]
    extension.response_received(live_response(), Request(URL), FakeSpider())
    assert crawler.engine.reasons == ["daily_budget"]  # one close only
    assert extension.count == 2  # nothing is counted after the close


def test_crawl_budget_ignores_cache_replays():
    extension, crawler = budget_extension(daily_pages=1)
    request = Request("https://threedecks.org/x", meta={"cache_timestamp": 123.0})
    extension.response_received(live_response(), request, FakeSpider())
    assert extension.count == 0
    assert crawler.engine.reasons == []


def test_crawl_budget_closes_when_the_window_has_ended():
    import time

    extension, crawler = budget_extension(stop_at=time.time() - 1)
    extension.response_received(live_response(), Request(URL), FakeSpider())
    assert crawler.engine.reasons == ["window_closed"]
    assert extension.count == 1
    extension.response_received(live_response(), Request(URL), FakeSpider())
    assert crawler.engine.reasons == ["window_closed"]  # one close only
