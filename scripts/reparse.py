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
from threedecks.parsing.actions import (
    ACTION_PARSER_VERSION,
    is_action_index_page,
    is_action_not_found,
    is_action_page,
    parse_action,
    parse_action_index,
)
from threedecks.parsing.fleets import (
    FLEET_PARSER_VERSION,
    is_fleet_not_found,
    is_fleet_page,
    is_fleetlist_index_page,
    parse_fleet,
    parse_fleet_index,
)
from threedecks.parsing.ship_page import is_not_found_page, is_ship_page, parse_ship
from threedecks.state import StateStore, utc_iso

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"
KINDS = ("ship", "action", "action_index", "fleet", "fleet_index", "all")


def display_type(url: str | None) -> str | None:
    """The exact ``display_type`` of a cached URL (``show_fleet`` is a prefix of
    ``show_fleetlist``, so a substring test would confuse the two)."""
    from urllib.parse import parse_qs, urlparse

    values = parse_qs(urlparse(url or "").query).get("display_type") or []
    return values[0] if values else None


def is_search_redirect(response) -> bool:
    """A missing ship id: the cache holds the 302 to the ship search, not that page.

    The live spider follows the redirect and sees "Find a ship"; a reparse sees
    only the redirect's empty body, which is not an incomplete ship page.
    """
    location = response.headers.get("Location") or b""
    return 300 <= response.status < 400 and b"display_type=ships_search" in location


def is_action_redirect(response) -> bool:
    """A missing action id: the cache holds the 302 to the action search."""
    location = response.headers.get("Location") or b""
    return 300 <= response.status < 400 and b"display_type=select_action" in location


def iter_cached(httpcache: Path, kind: str):
    """Yield ``(kind, response, stored_at)`` for every cached page of ``kind``."""
    conn = sqlite3.connect(str(httpcache))
    conn.row_factory = sqlite3.Row
    try:
        for row in conn.execute("SELECT url, stored_at, data FROM responses"):
            url = row["url"] or ""
            if kind in ("ship", "all") and "show_ship" in url:
                yield "ship", load_cached_response(row["data"]), row["stored_at"]
            elif kind in ("action", "all") and "show_battle" in url:
                yield "action", load_cached_response(row["data"]), row["stored_at"]
            elif kind in ("action_index", "all") and "select_action" in url:
                yield "action_index", load_cached_response(row["data"]), row["stored_at"]
            elif kind in ("fleet", "all") and display_type(url) == "show_fleet":
                yield "fleet", load_cached_response(row["data"]), row["stored_at"]
            elif kind in ("fleet_index", "all") and display_type(url) == "show_fleetlist":
                yield "fleet_index", load_cached_response(row["data"]), row["stored_at"]
    finally:
        conn.close()


def reparse_ship(store, response, stored_at, only_id) -> str:
    td_id = extract_id(response.url)
    if td_id is None or (only_id is not None and td_id != only_id):
        return "skip"
    selector = Selector(text=response.text)
    if is_search_redirect(response):
        store.mark_status(td_id, "not_found")
        return "skip"
    if response.status != 200:
        return "skip"  # a fetch error: its frontier row stays retryable
    if is_not_found_page(selector):
        store.mark_status(td_id, "not_found")
        return "skip"
    if not is_ship_page(selector):
        store.mark_status(td_id, "parse_error", error="incomplete page on reparse")
        return "skip"
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
        return "fail"
    if record.td_id is None:
        record.td_id = td_id
    store.save_ship(record)
    return "replay"


def reparse_action(store, response, stored_at, only_id) -> str:
    battle_id = extract_id(response.url)
    if battle_id is None or (only_id is not None and battle_id != only_id):
        return "skip"
    if is_action_redirect(response):
        store.mark_page_status("action", str(battle_id), "not_found")
        return "skip"
    if response.status != 200:
        return "skip"
    selector = Selector(text=response.text)
    if is_action_not_found(selector):
        store.mark_page_status("action", str(battle_id), "not_found")
        return "skip"
    if not is_action_page(selector):
        store.mark_page_status(
            "action", str(battle_id), "parse_error", error="incomplete page on reparse"
        )
        return "skip"
    try:
        record = parse_action(
            selector,
            response.url,
            fetched_at=utc_iso(stored_at),
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            parser_version=ACTION_PARSER_VERSION,
        )
    except Exception as exc:
        store.mark_page_status("action", str(battle_id), "parse_error", error=repr(exc)[:500])
        return "fail"
    if record.battle_id is None:
        record.battle_id = battle_id
    store.save_action(record)
    return "replay"


def reparse_action_index(store, response, stored_at, only_id) -> str:
    if response.status != 200:
        return "skip"
    selector = Selector(text=response.text)
    if not is_action_index_page(selector):
        return "skip"  # e.g. the redirect target's find page, or a ship page
    try:
        page = parse_action_index(selector)
    except Exception:  # nothing to key the failure to; report it and move on
        return "fail"
    if page.page is None:
        return "skip"
    store.save_action_index_page(str(page.page), page.rows)
    return "replay"


def reparse_fleet(store, response, stored_at, only_id) -> str:
    fleet_id = extract_id(response.url)
    if fleet_id is None or (only_id is not None and fleet_id != only_id):
        return "skip"
    if response.status != 200:
        return "skip"  # a fetch error: its frontier row stays retryable
    selector = Selector(text=response.text)
    if is_fleet_not_found(selector):
        store.mark_page_status("fleet", str(fleet_id), "not_found")
        return "skip"
    if not is_fleet_page(selector):
        store.mark_page_status(
            "fleet", str(fleet_id), "parse_error", error="incomplete page on reparse"
        )
        return "skip"
    try:
        record = parse_fleet(
            selector,
            response.url,
            fetched_at=utc_iso(stored_at),
            content_sha256=hashlib.sha256(response.body).hexdigest(),
            parser_version=FLEET_PARSER_VERSION,
        )
    except Exception as exc:  # keep going; the row says what failed
        store.mark_page_status("fleet", str(fleet_id), "parse_error", error=repr(exc)[:500])
        return "fail"
    store.save_fleet(record)
    return "replay"


def reparse_fleet_index(store, response, stored_at, only_id) -> str:
    if response.status != 200:
        return "skip"
    selector = Selector(text=response.text)
    if not is_fleetlist_index_page(selector):
        return "skip"  # e.g. the ship or action search page
    try:
        rows = parse_fleet_index(selector)
    except Exception:  # nothing to key the failure to; report it and move on
        return "fail"
    store.save_fleet_index(rows)
    return "replay"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--id", type=int, default=None, help="reparse only this id")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--kind", choices=KINDS, default="all",
                        help="which cached page types to reparse")
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    store = StateStore(data_dir / "state.sqlite")
    replayed = skipped = failed = 0
    handlers = {
        "ship": reparse_ship,
        "action": reparse_action,
        "action_index": reparse_action_index,
        "fleet": reparse_fleet,
        "fleet_index": reparse_fleet_index,
    }
    try:
        for kind, response, stored_at in iter_cached(data_dir / "httpcache.sqlite", args.kind):
            outcome = handlers[kind](store, response, stored_at, args.id)
            if outcome == "replay":
                replayed += 1
            elif outcome == "fail":
                failed += 1
            else:
                skipped += 1
            if args.limit and replayed + skipped + failed >= args.limit:
                break
    finally:
        store.close()
    print(f"reparsed {replayed} page(s); {skipped} skipped; {failed} parser error(s)")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
