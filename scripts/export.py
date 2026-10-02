"""Export the state database to JSONL and Parquet (Plan 6).

    uv run python scripts/export.py [--data-dir data/threedecks] [--out DIR]

``ships.jsonl`` and ``captures.jsonl`` are the lossless exports (one record per
line); the Parquet files carry a flattened, scalar view for analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from threedecks.state import StateStore

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def flatten_ship(record: dict) -> dict:
    dates = {
        item.get("label"): (item.get("date") or {}).get("iso")
        for item in record.get("lifecycle", [])
    }
    return {
        "td_id": record.get("td_id"),
        "name": record.get("name"),
        "nation_id": record.get("nation_id"),
        "nation_name": record.get("nation_name"),
        "operator": record.get("operator"),
        "nominal_guns": record.get("nominal_guns"),
        "category": record.get("category"),
        "ship_type": record.get("ship_type"),
        "ship_type_id": record.get("ship_type_id"),
        "rig": record.get("rig"),
        "how_acquired": record.get("how_acquired"),
        "class_id": record.get("class_id"),
        "class_name": record.get("class_name"),
        "launched": dates.get("Launched"),
        "captured": dates.get("Captured"),
        "sold": dates.get("Sold"),
        "history_count": len(record.get("history", [])),
        "source_count": len(record.get("sources", [])),
        "url": record.get("url"),
        "fetched_at": record.get("fetched_at"),
        "content_sha256": record.get("content_sha256"),
        "parser_version": record.get("parser_version"),
    }


def flatten_capture(row: dict) -> dict:
    return {
        "captured_td_id": row.get("captured_td_id"),
        "captured_label": row.get("captured_label"),
        "date_raw": row.get("date", {}).get("raw"),
        "date_iso": row.get("date", {}).get("iso"),
        "captor_td_ids": ",".join(str(i) for i in row.get("captor_td_ids", [])),
        "place_text": row.get("place_text"),
        "from_nation_id": row.get("from_nation_id"),
        "by_nation_id": row.get("by_nation_id"),
        "war_id": row.get("war_id"),
    }


def write_jsonl(path: Path, records) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_parquet(path: Path, rows: list[dict]) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return False
    pd.DataFrame(rows).to_parquet(path, index=False)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out) if args.out else data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = StateStore(data_dir / "state.sqlite")
    try:
        ships = list(store.iter_ships())
        captures = list(store.iter_captures())
    finally:
        store.close()

    write_jsonl(out_dir / "ships.jsonl", ships)
    write_jsonl(out_dir / "captures.jsonl", captures)
    parquet = write_parquet(out_dir / "ships.parquet", [flatten_ship(s) for s in ships])
    write_parquet(out_dir / "captures.parquet", [flatten_capture(c) for c in captures])
    print(
        f"exported {len(ships)} ships and {len(captures)} captures to {out_dir}"
        + ("" if parquet else " (Parquet skipped: pandas/pyarrow unavailable)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
