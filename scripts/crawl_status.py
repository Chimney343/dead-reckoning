"""Report crawl progress and an ETA from ``state.sqlite``.

    uv run python scripts/crawl_status.py [--data-dir data/threedecks]
"""

from __future__ import annotations

import argparse
from pathlib import Path

from threedecks.state import StateStore

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    args = parser.parse_args(argv)

    store = StateStore(Path(args.data_dir) / "state.sqlite")
    try:
        counts = store.counts_by_status()
        total = sum(counts.values())
        print(f"frontier rows : {total}")
        for status in ("done", "pending", "not_found", "error", "parse_error"):
            if counts.get(status):
                print(f"  {status:<11}: {counts[status]}")
        print(f"ships stored  : {store.ship_count()}")
        print(f"captures rows : {store.capture_count()}")

        last_run = None
        if total:
            rows = store._conn.execute(  # noqa: SLF001 - status script reads raw rows
                "SELECT * FROM runs ORDER BY run_id DESC LIMIT 1"
            ).fetchall()
            last_run = dict(rows[0]) if rows else None
        if last_run and last_run.get("started_at"):
            print(
                f"last run      : {last_run['spider']} started {last_run['started_at']} "
                f"({last_run.get('pages_fetched', 0)} pages fetched from the site, "
                f"{last_run.get('close_reason')})"
            )
            pages = last_run.get("pages_fetched") or 0
            if pages and last_run.get("finished_at"):
                from datetime import datetime

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                try:
                    elapsed = (
                        datetime.strptime(last_run["finished_at"], fmt)
                        - datetime.strptime(last_run["started_at"], fmt)
                    ).total_seconds()
                except (TypeError, ValueError):
                    elapsed = 0
                if elapsed > 0:
                    pph = pages * 3600 / elapsed
                    remaining = counts.get("pending", 0) + counts.get("error", 0)
                    eta_h = remaining / pph if pph else 0
                    print(f"throughput    : {pph:.0f} pages/hour; ETA {eta_h:.1f} h")
        return 0
    finally:
        store.close()


if __name__ == "__main__":
    raise SystemExit(main())
