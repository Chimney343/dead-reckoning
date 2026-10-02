"""Item pipelines: validation, then the crash-safe state upsert (Plan 4, 4.3).

Scrapy feeds are not used: they append, so a resumed run would duplicate
records. Instead :class:`StatePipeline` upserts each item into ``state.sqlite``,
and :meth:`StateStore.save_ship` marks the frontier row ``done`` in the same
transaction.
"""

from __future__ import annotations

import logging
from pathlib import Path

from scrapy.exceptions import DropItem

from threedecks.items import CaptureRow, ShipRecord
from threedecks.state import StateStore

logger = logging.getLogger(__name__)


class ValidationPipeline:
    """Drop items that cannot be stored meaningfully."""

    def process_item(self, item, spider):
        if isinstance(item, ShipRecord):
            if item.td_id is None:
                raise DropItem("ship record without a td_id")
            if not item.name:
                raise DropItem(f"ship record {item.td_id} without a name")
        elif isinstance(item, CaptureRow):
            if not item.date.raw:
                raise DropItem("capture row without a date")
        return item


class StatePipeline:
    """Upsert every item into the SQLite state store."""

    def __init__(self, data_dir: str | Path) -> None:
        self.data_dir = Path(data_dir)
        self.store: StateStore | None = None

    @classmethod
    def from_crawler(cls, crawler):
        return cls(crawler.settings["DATA_DIR"])

    def open_spider(self, spider) -> None:
        self.store = StateStore(self.data_dir / "state.sqlite")

    def close_spider(self, spider) -> None:
        if self.store is not None:
            self.store.close()
            self.store = None

    def process_item(self, item, spider):
        if self.store is None:  # defensive: pipelines opened outside Scrapy
            self.store = StateStore(self.data_dir / "state.sqlite")
        if isinstance(item, ShipRecord):
            self.store.save_ship(item)
        elif isinstance(item, CaptureRow):
            self.store.save_capture(item)
        return item
