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

from threedecks.items import ActionIndexRow, ActionRecord, CaptureRow, ShipRecord

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
CREATE TABLE IF NOT EXISTS page_frontier (
    kind TEXT NOT NULL,          -- e.g. 'action', 'action_index', 'fleet', 'fleet_index'
    page_key TEXT NOT NULL,      -- entity id or index page number, as text
    discovered_by TEXT,
    depth INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | not_found | error | parse_error
    attempts INTEGER NOT NULL DEFAULT 0,
    http_status INTEGER, last_error TEXT, updated_at TEXT,
    PRIMARY KEY (kind, page_key)
);
CREATE INDEX IF NOT EXISTS page_frontier_status ON page_frontier (kind, status);
CREATE TABLE IF NOT EXISTS actions (
    battle_id INTEGER PRIMARY KEY,
    record_json TEXT NOT NULL,
    parser_version TEXT,
    content_sha256 TEXT,
    fetched_at TEXT
);
CREATE TABLE IF NOT EXISTS action_index (
    battle_id INTEGER PRIMARY KEY,
    row_json TEXT NOT NULL
);
"""


def utc_iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def utcnow() -> str:
    return utc_iso(time.time())


def capture_key(row: CaptureRow) -> str:
    """Stable key for a capture row: query + captured ship + raw date + captors.

    The captors are part of it because the list can name the same ship and date
    twice, once per captor (Diligencia, 1804/12/07: Pique, and Diana).
    """
    return "|".join(
        str(part)
        for part in (
            row.from_nation_id,
            row.by_nation_id,
            row.war_id,
            row.captured_td_id,
            row.date.raw,
            ",".join(str(i) for i in sorted(row.captor_td_ids)) or row.captor_text,
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

    def release_attempts(self, td_ids, reason: str = "network down; attempt not counted") -> None:
        """Give back one attempt each: the failure was not the page's fault."""
        now = utcnow()
        with self._conn:
            self._conn.executemany(
                "UPDATE frontier SET attempts = MAX(attempts - 1, 0), status = 'pending', "
                "last_error = ?, updated_at = ? "
                "WHERE td_id = ?",
                [(reason, now, int(td_id)) for td_id in td_ids],
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

    # -- generic page frontier (Task S3) ----------------------------------
    def seed_pages(self, kind: str, keys, discovered_by: str, depth: int = 0) -> list[str]:
        """Insert page seeds that are not already known. Returns the new keys, input order."""
        now = utcnow()
        new: list[str] = []
        with self._conn:
            for key in keys:
                key = str(key)
                cur = self._conn.execute(
                    "INSERT OR IGNORE INTO page_frontier "
                    "(kind, page_key, discovered_by, depth, status, attempts, updated_at) "
                    "VALUES (?, ?, ?, ?, 'pending', 0, ?)",
                    (kind, key, discovered_by, depth, now),
                )
                if cur.rowcount:
                    new.append(key)
        return new

    def pending_pages(self, kind: str, max_attempts: int = 3):
        """Stream page keys that still need a fetch: pending or retryable error."""
        cursor = self._conn.execute(
            "SELECT page_key FROM page_frontier "
            "WHERE kind = ? AND status IN ('pending', 'error') AND attempts < ? "
            "ORDER BY CAST(page_key AS INTEGER), page_key",
            (kind, max_attempts),
        )
        for row in cursor:
            yield row["page_key"]

    def page_status(self, kind: str, key) -> str | None:
        row = self._conn.execute(
            "SELECT status FROM page_frontier WHERE kind = ? AND page_key = ?",
            (kind, str(key)),
        ).fetchone()
        return row["status"] if row else None

    def page_attempts(self, kind: str, key) -> int:
        row = self._conn.execute(
            "SELECT attempts FROM page_frontier WHERE kind = ? AND page_key = ?",
            (kind, str(key)),
        ).fetchone()
        return row["attempts"] if row else 0

    def mark_page_status(
        self,
        kind: str,
        key,
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
                "INSERT INTO page_frontier "
                "(kind, page_key, discovered_by, depth, status, attempts, http_status, "
                " last_error, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(kind, page_key) DO UPDATE SET "
                " status = excluded.status, "
                " attempts = page_frontier.attempts + ?, "
                " http_status = excluded.http_status, "
                " last_error = excluded.last_error, "
                " updated_at = excluded.updated_at",
                (
                    kind,
                    str(key),
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

    def release_page_attempts(
        self, kind: str, keys, reason: str = "network down; attempt not counted"
    ) -> None:
        """Give back one attempt each: the failure was not the page's fault."""
        now = utcnow()
        with self._conn:
            self._conn.executemany(
                "UPDATE page_frontier SET attempts = MAX(attempts - 1, 0), status = 'pending', "
                "last_error = ?, updated_at = ? WHERE kind = ? AND page_key = ?",
                [(reason, now, kind, str(key)) for key in keys],
            )

    def page_counts_by_status(self, kind: str) -> dict[str, int]:
        rows = self._conn.execute(
            "SELECT status, COUNT(*) AS n FROM page_frontier WHERE kind = ? GROUP BY status",
            (kind,),
        ).fetchall()
        return {row["status"]: row["n"] for row in rows}

    def _page_done_sql(self, kind: str, key, now: str) -> None:
        """The "mark done" upsert for one page, without committing.

        A kind-specific ``save_*()`` calls this inside its own ``with self._conn``
        so the record and the done mark are written in one transaction.
        """
        self._conn.execute(
            "INSERT INTO page_frontier (kind, page_key, status, attempts, updated_at) "
            "VALUES (?, ?, 'done', 0, ?) "
            "ON CONFLICT(kind, page_key) DO UPDATE SET "
            " status = 'done', updated_at = excluded.updated_at",
            (kind, str(key), now),
        )

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

    def clear_captures(self, from_nation_id, by_nation_id, war_id) -> int:
        """Drop one query's capture rows before it is re-saved, so stale keys go."""
        prefix = f"{from_nation_id}|{by_nation_id}|{war_id}|"
        with self._conn:
            cur = self._conn.execute(
                "DELETE FROM captures WHERE substr(key, 1, ?) = ?", (len(prefix), prefix)
            )
        return cur.rowcount

    def capture_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM captures").fetchone()["n"]

    def iter_ships(self):
        for row in self._conn.execute("SELECT td_id, record_json FROM ships ORDER BY td_id"):
            yield json.loads(row["record_json"])

    def iter_captures(self):
        for row in self._conn.execute("SELECT row_json FROM captures ORDER BY key"):
            yield json.loads(row["row_json"])

    # -- actions (Three Decks actions plan 4.2) ---------------------------
    def save_action(self, record: ActionRecord) -> None:
        """Upsert the action record and mark the page done in one transaction."""
        if record.battle_id is None:
            raise ValueError("cannot save an action record without a battle_id")
        payload = json.dumps(asdict(record), ensure_ascii=False, sort_keys=True)
        now = utcnow()
        with self._conn:
            self._conn.execute(
                "INSERT INTO actions "
                "(battle_id, record_json, parser_version, content_sha256, fetched_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(battle_id) DO UPDATE SET "
                " record_json = excluded.record_json, "
                " parser_version = excluded.parser_version, "
                " content_sha256 = excluded.content_sha256, "
                " fetched_at = excluded.fetched_at",
                (
                    record.battle_id,
                    payload,
                    record.parser_version,
                    record.content_sha256,
                    record.fetched_at or now,
                ),
            )
            self._page_done_sql("action", str(record.battle_id), now)

    def save_action_index_page(self, page_key: str, rows: list[ActionIndexRow]) -> int:
        """Upsert the page's rows and mark the page done in one transaction.

        Returns how many rows were stored (rows without a battle id are skipped).
        """
        now = utcnow()
        stored = 0
        with self._conn:
            for row in rows:
                if row.battle_id is None:
                    continue
                payload = json.dumps(asdict(row), ensure_ascii=False, sort_keys=True)
                self._conn.execute(
                    "INSERT INTO action_index (battle_id, row_json) VALUES (?, ?) "
                    "ON CONFLICT(battle_id) DO UPDATE SET row_json = excluded.row_json",
                    (row.battle_id, payload),
                )
                stored += 1
            self._page_done_sql("action_index", str(page_key), now)
        return stored

    def get_action(self, battle_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT record_json FROM actions WHERE battle_id = ?", (battle_id,)
        ).fetchone()
        return json.loads(row["record_json"]) if row else None

    def iter_actions(self):
        for row in self._conn.execute("SELECT record_json FROM actions ORDER BY battle_id"):
            yield json.loads(row["record_json"])

    def iter_action_index(self):
        for row in self._conn.execute("SELECT row_json FROM action_index ORDER BY battle_id"):
            yield json.loads(row["row_json"])

    def action_count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) AS n FROM actions").fetchone()["n"]

    def history_battle_ids(self) -> list[int]:
        """Every battle id cited by a stored ship's history, sorted and unique."""
        ids: set[int] = set()
        for row in self._conn.execute("SELECT record_json FROM ships"):
            record = json.loads(row["record_json"])
            for event in record.get("history", []):
                ids.update(event.get("battle_ids", []))
        return sorted(ids)

    # -- runs --------------------------------------------------------------
    def close_open_runs(self) -> int:
        """Mark runs that never finished (killed, PC rebooted) as ``interrupted``.

        Their end time is the last frontier update before the next run began.
        """
        with self._conn:
            cur = self._conn.execute(
                "UPDATE runs SET close_reason = 'interrupted', finished_at = COALESCE("
                " (SELECT MAX(u) FROM ("
                "  SELECT f.updated_at AS u FROM frontier f"
                "   WHERE f.updated_at >= runs.started_at AND f.updated_at < COALESCE("
                "    (SELECT MIN(r.started_at) FROM runs r WHERE r.run_id > runs.run_id),"
                "    '9999')"
                "  UNION ALL"
                "  SELECT p.updated_at FROM page_frontier p"
                "   WHERE p.updated_at >= runs.started_at AND p.updated_at < COALESCE("
                "    (SELECT MIN(r.started_at) FROM runs r WHERE r.run_id > runs.run_id),"
                "    '9999')"
                " )),"
                " started_at) "
                "WHERE finished_at IS NULL"
            )
        return cur.rowcount

    def start_run(self, spider: str) -> int:
        self.close_open_runs()
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
