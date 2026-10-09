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

        print(f"actions stored: {store.action_count()}")
        for kind in ("action_index", "action"):
            kind_counts = store.page_counts_by_status(kind)
            total_kind = sum(kind_counts.values())
            detail = ", ".join(
                f"{status}: {n}" for status, n in sorted(kind_counts.items()) if n
            )
            print(f"  {kind:<13}: {total_kind} pages" + (f" ({detail})" if detail else ""))
        actions_run = store._conn.execute(  # noqa: SLF001 - status script reads raw rows
            "SELECT * FROM runs WHERE spider = 'actions' ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if actions_run:
            print(
                f"last actions  : started {actions_run['started_at']} "
                f"({actions_run['pages_fetched']} pages fetched from the site, "
                f"{actions_run['close_reason']})"
            )
            pages = actions_run["pages_fetched"] or 0
            if pages and actions_run["finished_at"]:
                from datetime import datetime

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                try:
                    elapsed = (
                        datetime.strptime(actions_run["finished_at"], fmt)
                        - datetime.strptime(actions_run["started_at"], fmt)
                    ).total_seconds()
                except (TypeError, ValueError):
                    elapsed = 0
                if elapsed > 0:
                    remaining = sum(
                        n
                        for status, n in store.page_counts_by_status("action").items()
                        if status in ("pending", "error")
                    )
                    pph = pages * 3600 / elapsed
                    if pph:
                        print(
                            f"actions ETA   : {pph:.0f} pages/hour; "
                            f"ETA {remaining / pph:.1f} h"
                        )

        print(f"fleets stored : {store.fleet_count()}")
        for kind in ("fleet_index", "fleet"):
            kind_counts = store.page_counts_by_status(kind)
            total_kind = sum(kind_counts.values())
            detail = ", ".join(
                f"{status}: {n}" for status, n in sorted(kind_counts.items()) if n
            )
            print(f"  {kind:<13}: {total_kind} pages" + (f" ({detail})" if detail else ""))
        fleets_run = store._conn.execute(  # noqa: SLF001 - status script reads raw rows
            "SELECT * FROM runs WHERE spider = 'fleets' ORDER BY run_id DESC LIMIT 1"
        ).fetchone()
        if fleets_run:
            print(
                f"last fleets   : started {fleets_run['started_at']} "
                f"({fleets_run['pages_fetched']} pages fetched from the site, "
                f"{fleets_run['close_reason']})"
            )
            pages = fleets_run["pages_fetched"] or 0
            if pages and fleets_run["finished_at"]:
                from datetime import datetime

                fmt = "%Y-%m-%dT%H:%M:%SZ"
                try:
                    elapsed = (
                        datetime.strptime(fleets_run["finished_at"], fmt)
                        - datetime.strptime(fleets_run["started_at"], fmt)
                    ).total_seconds()
                except (TypeError, ValueError):
                    elapsed = 0
                if elapsed > 0:
                    remaining = sum(
                        n
                        for status, n in store.page_counts_by_status("fleet").items()
                        if status in ("pending", "error")
                    )
                    pph = pages * 3600 / elapsed
                    if pph:
                        print(
                            f"fleets ETA    : {pph:.0f} pages/hour; "
                            f"ETA {remaining / pph:.1f} h"
                        )

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
