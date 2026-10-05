"""Re-run the ship-page parser over the HTTP cache, offline (Plan 4.3, step 7).

After a parser fix, this rewrites every cached ship record without touching the
network. The HTTP cache is the source of truth (rule 6), so a fix is replayed
across the whole crawl here and never by refetching. Each record keeps the
fetch time and body hash of its cached page.

    uv run python scripts/reparse.py [--data-dir data/threedecks] [--id N] [--limit N]
"""

from __future__ import annotations

import argparse
import hashlib
import sqlite3
from pathlib import Path

from parsel import Selector
from threedecks import PARSER_VERSION
from threedecks.cache import load_cached_response
from threedecks.items import extract_id
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship
from threedecks.state import StateStore, utc_iso

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def is_search_redirect(response) -> bool:
    """A missing ship id: the cache holds the 302 to the ship search, not that page.

    The live spider follows the redirect and sees "Find a ship"; a reparse sees
    only the redirect's empty body, which is not an incomplete ship page.
    """
    location = response.headers.get("Location") or b""
    return 300 <= response.status < 400 and b"display_type=ships_search" in location


def iter_cached_ships(httpcache: Path):
    """Yield ``(response, stored_at)`` for every cached ship page, bodies decoded."""
    conn = sqlite3.connect(str(httpcache))
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT url, stored_at, data FROM responses"):
            if "show_ship" not in (row["url"] or ""):
                continue
            yield load_cached_response(row["data"]), row["stored_at"]
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
    replayed = skipped = failed = 0
    try:
        for response, stored_at in iter_cached_ships(data_dir / "httpcache.sqlite"):
            td_id = extract_id(response.url)
            if td_id is None:
                continue
            if args.id is not None and td_id != args.id:
                continue
            selector = Selector(text=response.text)
            if is_search_redirect(response):
                store.mark_status(td_id, "not_found")
                skipped += 1
            elif response.status != 200:
                skipped += 1  # a fetch error: its frontier row stays retryable
            elif is_not_found_page(selector):
                store.mark_status(td_id, "not_found")
                skipped += 1
            elif not is_ship_page(selector):
                store.mark_status(td_id, "parse_error", error="incomplete page on reparse")
                skipped += 1
            else:
                try:
                    record = parse_ship(
                        selector,
                        response.url,
                        fetched_at=utc_iso(stored_at),
                        content_sha256=hashlib.sha256(response.body).hexdigest(),
                        parser_version=PARSER_VERSION,
                    )
                except Exception as exc:  # keep going; the row says what failed
                    store.mark_status(td_id, "parse_error", error=repr(exc)[:500])
                    failed += 1
                    continue
                if record.td_id is None:
                    record.td_id = td_id
                store.save_ship(record)
                replayed += 1
            if args.limit and replayed + skipped + failed >= args.limit:
                break
    finally:
        store.close()
    print(f"reparsed {replayed} ship page(s); {skipped} skipped; {failed} parser error(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
