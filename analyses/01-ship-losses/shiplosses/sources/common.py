"""Shared extractor helpers: provenance metadata and DataFrame assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from ..schema import LOSS_COLUMNS, loss_row


def load_meta(
    directory: Path,
    source_id: str,
    *,
    tier: str = "T3",
    licence: str = "Unknown",
    redistribute: bool = False,
    url: str = "",
) -> dict[str, object]:
    """Read the fetcher's ``_provenance.json`` for licence and tier."""
    meta: dict[str, object] = {
        "source": source_id,
        "tier": tier,
        "licence": licence,
        "redistribute": redistribute,
        "source_url": url,
    }
    path = directory / "_provenance.json"
    if path.exists():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
        if isinstance(data, dict):
            meta["source"] = data.get("id", source_id)
            meta["tier"] = data.get("tier", tier)
            meta["licence"] = data.get("licence", licence)
            meta["redistribute"] = bool(data.get("redistribute", redistribute))
            meta["source_url"] = data.get("url", url)
    return meta


def losses_frame(rows: list[dict]) -> pd.DataFrame:
    """Build a losses DataFrame with the exact schema, even when empty."""
    if not rows:
        return pd.DataFrame({column: [] for column in LOSS_COLUMNS})
    return pd.DataFrame([loss_row(**row) for row in rows])


def first(value: object, default: object = "") -> object:
    if value is None:
        return default
    text = str(value).strip()
    return text or default
