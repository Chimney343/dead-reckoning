"""Re-run the ship-page parser over the HTTP cache, offline (Plan 4.3, step 7).

After a parser fix, this rewrites every cached ship record without touching the
network. The HTTP cache is the source of truth (rule 6), so a fix is replayed
across the whole crawl here and never by refetching.

    uv run python scripts/reparse.py [--data-dir data/threedecks] [--id N] [--limit N]
"""

from __future__ import annotations

import argparse
import pickle
import sqlite3
import zlib
from pathlib import Path

from parsel import Selector
from threedecks.items import extract_id
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship
from threedecks.state import StateStore, utcnow

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def iter_cached_ships(httpcache: Path):
    conn = sqlite3.connect(str(httpcache))
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT fingerprint, url, data FROM responses"):
            if "show_ship" not in (row["url"] or ""):
                continue
            payload = pickle.loads(zlib.decompress(row["data"]))
            yield row["url"], payload
    finally:
        conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--id", type=int, default=None, help="reparse only this ship id")
    parser.add_argument("--limit", type=int, default=None)
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    store = StateStore(data_dir / "state.sqlite")
    replayed = skipped = 0
    try:
        for url, payload in iter_cached_ships(data_dir / "httpcache.sqlite"):
            td_id = extract_id(url)
            if td_id is None:
                continue
            if args.id is not None and td_id != args.id:
                continue
            body = payload.get("body", b"")
            selector = Selector(text=body.decode("utf-8", "replace"))
            if is_not_found_page(selector):
                store.mark_status(td_id, "not_found")
                skipped += 1
            elif not is_ship_page(selector):
                store.mark_status(
                    td_id, "parse_error", error="incomplete page on reparse"
                )
                skipped += 1
            else:
                record = parse_ship(selector, url, fetched_at=utcnow())
                if record.td_id is None:
                    record.td_id = td_id
                store.save_ship(record)
                replayed += 1
            if args.limit and replayed + skipped >= args.limit:
                break
    finally:
        store.close()
    print(f"reparsed {replayed} ship page(s); {skipped} skipped")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
