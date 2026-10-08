"""Crash-safe HTTP cache for the Three Decks crawler (Plan 4.3, step 5).

Scrapy's default filesystem cache writes metadata before the body, so a kill
mid-write can leave an entry that looks cached but has a truncated body (and
Scrapy serves a truncated body as if it were complete). This storage keeps each
response in a single SQLite row: the body and its metadata commit together, or
not at all. The row is keyed by the request fingerprint, which includes the POST
body, so captures and search POSTs are cached separately.

The HTTP cache is the source of truth for "fetch each page once" (rule 6):
re-parsing and resuming always read the cache.
"""

from __future__ import annotations

import gzip
import pickle
import sqlite3
import sys
import time
import zlib
from pathlib import Path

import brotli
from scrapy.extensions.httpcache import DummyPolicy
from scrapy.http import Request, Response
from scrapy.responsetypes import responsetypes
from scrapy.utils.httpobj import urlparse_cached
from scrapy.utils.response import response_from_dict

from threedecks.middlewares import is_blocked, is_challenge

_SCHEMA = """
CREATE TABLE IF NOT EXISTS responses (
    fingerprint TEXT PRIMARY KEY,
    spider TEXT,
    url TEXT,
    status INTEGER,
    stored_at REAL NOT NULL,
    data BLOB NOT NULL
);
"""


if sys.version_info >= (3, 14):
    from compression import zstd
else:  # a Scrapy dependency, like brotli
    from backports import zstd


def _inflate(body: bytes) -> bytes:
    try:
        return zlib.decompress(body)
    except zlib.error:  # raw deflate, without the zlib header
        return zlib.decompress(body, -zlib.MAX_WBITS)


_DECODERS = {
    b"gzip": gzip.decompress,
    b"x-gzip": gzip.decompress,
    b"deflate": _inflate,
    b"br": brotli.decompress,
    b"zstd": zstd.decompress,
}


def load_cached_response(data: bytes) -> Response:
    """Rebuild a cached response with its body decoded, as the spiders see it.

    The cache sits outside HttpCompressionMiddleware, so stored bodies are still
    encoded (the site serves zstd). Anything that reads the cache without Scrapy
    (``scripts/reparse.py``) must go through this.
    """
    response = response_from_dict(pickle.loads(zlib.decompress(data)))
    encodings = [
        encoding.strip().lower()
        for value in response.headers.getlist("Content-Encoding")
        for encoding in value.split(b",")
    ]
    if not encodings:
        return response
    body = response.body
    for encoding in reversed(encodings):  # the last encoding applied comes off first
        if encoding not in _DECODERS:
            raise ValueError(f"unsupported Content-Encoding {encoding!r} for {response.url}")
        body = _DECODERS[encoding](body)
    headers = response.headers.copy()
    del headers["Content-Encoding"]
    # The class was guessed from the encoded body; guess again from the decoded one.
    cls = responsetypes.from_args(headers=headers, url=response.url, body=body)
    return response.replace(cls=cls, body=body, headers=headers)


class ThreeDecksCachePolicy(DummyPolicy):
    """Cache every page forever, except robots.txt and block/challenge pages.

    With ``HTTPCACHE_EXPIRATION_SECS = 0`` a cached robots.txt would be obeyed
    for good, so a narrowed robots.txt would never take effect (rule 1); it is
    fetched once per run instead. A cached challenge or WAF block page would be
    replayed to every retry after a cool-off, and to every later run.
    """

    def should_cache_request(self, request: Request) -> bool:
        if urlparse_cached(request).path == "/robots.txt":
            return False
        return super().should_cache_request(request)

    def should_cache_response(self, response: Response, request: Request) -> bool:
        if is_challenge(response) or is_blocked(response):
            return False
        return super().should_cache_response(response, request)


class SqliteCacheStorage:
    """Implements Scrapy's cache storage interface over one SQLite file."""

    def __init__(self, settings) -> None:
        self.cachedir = Path(settings["HTTPCACHE_DIR"])
        self.expiration_secs = settings.getint("HTTPCACHE_EXPIRATION_SECS")
        self.db_path = self.cachedir / "httpcache.sqlite"
        self._conn: sqlite3.Connection | None = None
        self._fingerprinter = None

    def open_spider(self, spider) -> None:
        self.cachedir.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.db_path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # FULL: a power cut cannot drop a committed page, which would leave a
        # finished record that reparse.py could not rebuild. One flush per page.
        self._conn.execute("PRAGMA synchronous=FULL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._fingerprinter = spider.crawler.request_fingerprinter

    def close_spider(self, spider) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def _fingerprint(self, request: Request) -> str:
        return self._fingerprinter.fingerprint(request).hex()

    def retrieve_response(self, spider, request: Request) -> Response | None:
        row = self._conn.execute(
            "SELECT data, stored_at FROM responses WHERE fingerprint = ?",
            (self._fingerprint(request),),
        ).fetchone()
        if row is None:
            return None
        timestamp = row["stored_at"]
        if 0 < self.expiration_secs < time.time() - timestamp:
            return None
        request.meta["cache_timestamp"] = timestamp
        return response_from_dict(pickle.loads(zlib.decompress(row["data"])))

    def store_response(self, spider, request: Request, response: Response) -> None:
        # Serialise before opening the transaction: a failure here writes nothing.
        data = zlib.compress(pickle.dumps(response.to_dict(), protocol=4))
        with self._conn:
            self._conn.execute(
                "INSERT OR REPLACE INTO responses "
                "(fingerprint, spider, url, status, stored_at, data) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    self._fingerprint(request),
                    spider.name,
                    request.url,
                    response.status,
                    time.time(),
                    data,
                ),
            )

    def remove_response(self, spider, request: Request) -> None:
        """Drop an entry so a bad response is refetched on the next run."""
        with self._conn:
            self._conn.execute(
                "DELETE FROM responses WHERE fingerprint = ?",
                (self._fingerprint(request),),
            )
