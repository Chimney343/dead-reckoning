"""Shared helpers for harvesters."""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import core


def safe_stem(name: str) -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")
    return stem or "record"


def save_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def file_record(path: Path, url: str | None = None, **extra) -> dict:
    record = {
        "bytes": path.stat().st_size,
        "sha256": core.sha256_file(path),
        "fetched_at": core.utcnow(),
        "skipped": False,
    }
    if url:
        record["url"] = url
    record.update(extra)
    return record
