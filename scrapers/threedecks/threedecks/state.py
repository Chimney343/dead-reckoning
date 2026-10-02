"""Crash-safe crawl state in SQLite (Plan 4.3).

One file holds the frontier, the parsed records and the run log. WAL mode plus
one transaction per page mean a kill can lose at most the page in flight:

* a seed is inserted (``INSERT OR IGNORE``) before its request is scheduled, so
  discovered work survives a crash;
* :meth:`StateStore.save_ship` upserts the record and marks the frontier row
  ``done`` in a single transaction, so a page is never ``done`` without a record.

Resuming is therefore just re-running the same spider: ``start_requests`` reads
the pending rows back from this store.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict
from pathlib import Path

from threedecks.items import CaptureRow, ShipRecord

_SCHEMA = """
CREATE TABLE IF NOT EXISTS frontier (
    td_id INTEGER PRIMARY KEY,
    discovered_by TEXT,
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER,
    last_error TEXT,
    updated_at TEXT
);
CREATE TABLE IF NOT EXISTS ships (
    td_id INTEGER PRIMARY KEY,
    record_json TEXT NOT NULL,
    parser_version TEXT,
    content_sha256 TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS captures (
    key TEXT PRIMARY KEY,
    row_json TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    run_id INTEGER PRIMARY KEY AUTOINCREMENT,
    spider TEXT,
    started_at TEXT,
    finished_at TEXT,
    close_reason TEXT,
    pages_fetched INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS frontier_status ON frontier (status, td_id);
"""


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def capture_key(row: CaptureRow) -> str:
    """Stable key for a capture row: query + captured ship + raw date."""
    return "|".join(
        str(part)
        for part in (
            row.from_nation_id,
            row.by_nation_id,
            row.war_id,
            row.captured_td_id,
            row.date.raw,
        )
    )


class StateStore:
    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        if self.path.parent and str(self.path.parent) != ".":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self.path))
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    # -- lifecycle ---------------------------------------------------------
    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> StateStore:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- frontier ----------------------------------------------------------
    def seed(self, td_ids, discovered_by: str, depth: int = 0) -> int:
        """Insert seeds that are not already known. Returns how many were new."""
        now = utcnow()
        inserted = 0
        with self._conn:
            for td_id in td_ids:
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO frontier "
                    "(td_id, discovered_by, depth, status, attempts, updated_at) "
                    "VALUES (?, ?, ?, 'pending', 0, ?)",
                    (int(td_id), discovered_by, depth, now),
                )
                inserted += cur.rowcount
        return inserted

    def pending_ids(self, max_attempts: int = 3):
        """Stream ids that still need a fetch: pending or retryable error."""
        cursor = self._conn.execute(
            "SELECT td_id FROM frontier "
            "WHERE status IN ('pending', 'error') AND attempts < ? "
            "ORDER BY td_id",
            (max_attempts,),
        )
        for row in cursor:
            yield row["td_id"]

    def status(self, td_id: int) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM frontier WHERE td_id = ?", (td_id,)
        ).fetchone()
        return row["status"] if row else None

    def attempts(self, td_id: int) -> int:
        row = self._conn.execute(
            "SELECT attempts FROM frontier WHERE td_id = ?", (td_id,)
        ).fetchone()
        return row["attempts"] if row else 0

    def mark_status(
        self,
        td_id: int,
        status: str,
        *,
        http_status: int | None = None,
        error: str | None = None,
        increment_attempts: bool = False,
        discovered_by: str | None = None,
        depth: int = 0,
    ) -> None:
        now = utcnow()
        increment = 1 if increment_attempts else 0
        with self._conn:
            self._conn.execute(
                "INSERT INTO frontier "
                "(td_id, discovered_by, depth, status, attempts, http_status, "
                " last_error, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(td_id) DO UPDATE SET "
                " status = excluded.status, "
                " attempts = frontier.attempts + ?, "
                " http_status = excluded.http_status, "
                " last_error = excluded.last_error, "
                " updated_at = excluded.updated_at",
                (
                    int(td_id),
                    discovered_by,
                    depth,
                    status,
                    increment,
                    http_status,
                    error,
                    now,
                    increment,
                ),
            )

    def counts_by_status(self) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM frontier GROUP BY status"
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def max_td_id(self) -> int | None:
        row = self._conn.execute("SELECT MAX(td_id) AS m FROM frontier").fetchone()
        return row["m"] if row and row["m"] is not None else None

    def trailing_not_found(self) -> int:
        """Consecutive ``not_found`` rows from the highest id down.

        This is the Tier C upward-scan stop position; because it is derived from
        the frontier, it survives a restart.
        """
        count = 0
        for row in self._conn.execute("SELECT status FROM frontier ORDER BY td_id DESC"):
            if row["status"] != "not_found":
                break
            count += 1
        return count

    # -- records -----------------------------------------------------------
    def save_ship(self, record: ShipRecord) -> None:
        """Upsert the record and mark the page done in one transaction."""
        if record.td_id is None:
            raise ValueError("cannot save a ship record without a td_id")
        payload = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
        now = utcnow()
        with self._conn:
            self._conn.execute(
                "INSERT INTO ships "
                "(td_id, record_json, parser_version, content_sha256, fetched_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(td_id) DO UPDATE SET "
                " record_json = excluded.record_json, "
                " parser_version = excluded.parser_version, "
                " content_sha256 = excluded.content_sha256, "
                " fetched_at = excluded.fetched_at",
                (
                    record.td_id,
                    payload,
                    record.parser_version,
                    record.content_sha256,
                    record.fetched_at or now,
                ),
            )
            self._conn.execute(
                "INSERT INTO frontier (td_id, status, attempts, updated_at) "
                "VALUES (?, 'done', 0, ?) "
                "ON CONFLICT(td_id) DO UPDATE SET "
                " status = 'done', updated_at = excluded.updated_at",
                (record.td_id, now),
            )

    def get_ship(self, td_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT record_json FROM ships WHERE td_id = ?", (td_id,)
        ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def ship_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM ships").fetchone()["n"]

    def save_capture(self, row: CaptureRow) -> None:
        payload = json.dumps(asdict(row), ensure_ascii=False, sort_keys=True)
        with self._conn:
            self._conn.execute(
                "INSERT INTO captures (key, row_json) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET row_json = excluded.row_json",
                (capture_key(row), payload),
            )

    def capture_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM captures").fetchone()["n"]

    def iter_ships(self):
        for row in self._conn.execute("SELECT td_id, record_json FROM ships ORDER BY td_id"):
            yield json.loads(row["record_json"])

    def iter_captures(self):
        for row in self._conn.execute("SELECT row_json FROM captures ORDER BY key"):
            yield json.loads(row["row_json"])

    # -- runs --------------------------------------------------------------
    def start_run(self, spider: str) -> int:
        with self._conn:
            cur = self._conn.execute(
                "INSERT INTO runs (spider, started_at, pages_fetched) VALUES (?, ?, 0)",
                (spider, utcnow()),
            )
        return int(cur.lastrowid)

    def finish_run(
        self, run_id: int, *, close_reason: str | None = None, pages_fetched: int = 0
    ) -> None:
        with self._conn:
            self._conn.execute(
                "UPDATE runs SET finished_at = ?, close_reason = ?, pages_fetched = ? "
                "WHERE run_id = ?",
                (utcnow(), close_reason, pages_fetched, run_id),
            )

    def get_run(self, run_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        return dict(row) if row else None
