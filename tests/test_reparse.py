"""reparse.py replays the cache offline (Plan 4.3, step 7).

The cache stores bodies as the site sent them; Three Decks serves zstd, so a
reparse that skipped decoding would mark every page parse_error.
"""

from __future__ import annotations

import gzip
import hashlib
import pickle
import sqlite3
import zlib
from pathlib import Path

import pytest
from backports import zstd
from scrapy.http import HtmlResponse
from threedecks.cache import _SCHEMA, load_cached_response
from threedecks.state import StateStore

from scripts.reparse import main as reparse_main

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
URL = "https://threedecks.org/index.php?display_type=show_ship&id=1234"
STORED_AT = 1_790_000_000.0


def cache_row(
    html: bytes, encoding: str | None, *, status: int = 200, headers: dict | None = None
) -> bytes:
    headers = {"Content-Type": "text/html; charset=UTF-8", **(headers or {})}
    body = html
    if encoding == "zstd":
        body = zstd.compress(html)
    elif encoding == "gzip":
        body = gzip.compress(html)
    if encoding:
        headers["Content-Encoding"] = encoding
    response = HtmlResponse(url=URL, body=body, headers=headers, status=status)
    return zlib.compress(pickle.dumps(response.to_dict(), protocol=4))


def reparse_one_cached(tmp_path, row: bytes, status: int, frontier_status: str) -> str:
    """Reparse a cache holding one response for ship 1234; return its frontier status."""
    cache = sqlite3.connect(tmp_path / "httpcache.sqlite")
    cache.executescript(_SCHEMA)
    with cache:
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp", "ships_all", URL, status, STORED_AT, row),
        )
    cache.close()
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_status(1234, frontier_status)
    store.close()

    reparse_main(["--data-dir", str(tmp_path)])

    store = StateStore(tmp_path / "state.sqlite")
    try:
        return store.status(1234)
    finally:
        store.close()


# What the cache really holds for a missing id: the redirect, not the page it leads to.
REDIRECT_STUB = b"<html><head><title>&nbsp;</title></head><body></body></html>"
SEARCH = "https://threedecks.org/index.php?display_type=ships_search"


def test_reparse_marks_a_redirect_to_the_ship_search_not_found(tmp_path):
    row = cache_row(REDIRECT_STUB, "zstd", status=302, headers={"Location": SEARCH})
    assert reparse_one_cached(tmp_path, row, 302, "pending") == "not_found"


def test_reparse_leaves_a_cached_server_error_retryable(tmp_path):
    # Older caches hold Cloudflare 520 pages; parse_error would end the retries.
    page = b"<html><head><title>520: Web server is returning an unknown error</title></head></html>"
    row = cache_row(page, None, status=520)
    assert reparse_one_cached(tmp_path, row, 520, "error") == "error"


@pytest.mark.parametrize("encoding", [None, "gzip", "zstd"])
def test_cached_bodies_are_decoded(encoding):
    html = (FIXTURES / "ship_full.html").read_bytes()
    response = load_cached_response(cache_row(html, encoding))
    assert response.body == html
    assert "LaunchName" in response.text  # a text response, not a binary one
    assert not response.headers.get("Content-Encoding")


def test_reparse_decodes_zstd_and_keeps_provenance(tmp_path):
    html = (FIXTURES / "ship_full.html").read_bytes()
    cache = sqlite3.connect(tmp_path / "httpcache.sqlite")
    cache.executescript(_SCHEMA)
    with cache:
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp", "ships_all", URL, 200, STORED_AT, cache_row(html, "zstd")),
        )
    cache.close()
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_status(1234, "done")
    store.close()

    assert reparse_main(["--data-dir", str(tmp_path)]) == 0

    store = StateStore(tmp_path / "state.sqlite")
    try:
        assert store.status(1234) == "done"
        record = store.get_ship(1234)
        assert record["name"]
        assert record["content_sha256"] == hashlib.sha256(html).hexdigest()
        assert record["fetched_at"] == "2026-09-21T14:13:20Z"  # the cache's stored_at
    finally:
        store.close()


# --- actions (Task A8) ------------------------------------------------------

ACTION_URL = "https://threedecks.org/index.php?display_type=show_battle&id={id}"
SELECT_ACTION = "https://threedecks.org/index.php?display_type=select_action"


def cache_row_for(url: str, html: bytes, *, status: int = 200, headers: dict | None = None,
                  encoding: str = "zstd") -> bytes:
    all_headers = {"Content-Type": "text/html; charset=UTF-8", **(headers or {})}
    body = zstd.compress(html) if encoding == "zstd" else html
    if encoding == "zstd":
        all_headers["Content-Encoding"] = "zstd"
    response = HtmlResponse(url=url, body=body, headers=all_headers, status=status)
    return zlib.compress(pickle.dumps(response.to_dict(), protocol=4))


def test_reparse_action_page_and_redirect(tmp_path):
    html = (FIXTURES / "action_minimal.html").read_bytes()
    cache = sqlite3.connect(tmp_path / "httpcache.sqlite")
    cache.executescript(_SCHEMA)
    with cache:
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp1", "actions", ACTION_URL.format(id=42), 200, STORED_AT,
             cache_row_for(ACTION_URL.format(id=42), html)),
        )
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp2", "actions", ACTION_URL.format(id=999), 302, STORED_AT,
             cache_row_for(ACTION_URL.format(id=999), b"", status=302,
                           headers={"Location": SELECT_ACTION}, encoding=None)),
        )
    cache.close()
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_page_status("action", "42", "pending")
    store.mark_page_status("action", "999", "pending")
    store.close()

    assert reparse_main(["--data-dir", str(tmp_path), "--kind", "action"]) == 0

    store = StateStore(tmp_path / "state.sqlite")
    try:
        assert store.page_status("action", "42") == "done"
        assert store.get_action(42)["battle_id"] == 42
        assert store.page_status("action", "999") == "not_found"
    finally:
        store.close()


# --- fleets (Task FL8) ------------------------------------------------------


FLEET_URL = "https://threedecks.org/index.php?display_type=show_fleet&id={id}"
FLEETLIST = "https://threedecks.org/index.php?display_type=show_fleetlist"


def test_reparse_fleet_page(tmp_path):
    html = (FIXTURES / "fleet_full.html").read_bytes()
    cache = sqlite3.connect(tmp_path / "httpcache.sqlite")
    cache.executescript(_SCHEMA)
    with cache:
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp1", "fleets", FLEET_URL.format(id=555), 200, STORED_AT,
             cache_row_for(FLEET_URL.format(id=555), html)),
        )
    cache.close()
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_page_status("fleet", "555", "pending")
    store.close()

    assert reparse_main(["--data-dir", str(tmp_path), "--kind", "fleet"]) == 0

    store = StateStore(tmp_path / "state.sqlite")
    try:
        assert store.page_status("fleet", "555") == "done"
        assert store.get_fleet(555)["fleet_id"] == 555
        assert store.get_fleet(555)["name"] == "Example Fleet"
    finally:
        store.close()


def test_reparse_fleet_index(tmp_path):
    html = (FIXTURES / "fleetlist_index.html").read_bytes()
    cache = sqlite3.connect(tmp_path / "httpcache.sqlite")
    cache.executescript(_SCHEMA)
    with cache:
        cache.execute(
            "INSERT INTO responses VALUES (?, ?, ?, ?, ?, ?)",
            ("fp1", "fleets", FLEETLIST, 200, STORED_AT,
             cache_row_for(FLEETLIST, html)),
        )
    cache.close()
    store = StateStore(tmp_path / "state.sqlite")
    store.mark_page_status("fleet_index", "1", "pending")
    store.close()

    assert reparse_main(["--data-dir", str(tmp_path), "--kind", "fleet_index"]) == 0

    store = StateStore(tmp_path / "state.sqlite")
    try:
        assert store.page_status("fleet_index", "1") == "done"
        assert [row["fleet_id"] for row in store.iter_fleet_index()] == [69, 132, 139]
    finally:
        store.close()
