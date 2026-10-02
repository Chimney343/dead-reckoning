"""Layer 4-6: validation and the state pipeline (Plan 4, 4.3 step 3)."""

from __future__ import annotations

import pytest
from scrapy.exceptions import DropItem
from scrapy.settings import Settings
from threedecks.items import CaptureRow, ShipRecord
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
