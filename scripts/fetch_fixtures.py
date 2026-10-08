"""Polite fetch of the real fixture pages into ``tests/fixtures/real/``.

Run once from the repo root::

    uv run python scripts/fetch_fixtures.py

One request every 5 s, one at a time, with an identifiable User-Agent. Pages
already on disk are skipped, so a re-run costs nothing. ``tests/fixtures/real/``
is gitignored: these pages are used for local golden tests only and are never
republished.

The fixture list is not exhaustive on purpose. It covers the pages needed to
pin the parsers and to answer the Phase 1 open questions (the not-found
signature and the search-results markup).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx
from threedecks.ua import MISSING_CONTACT_HELP, build_user_agent, contact

BASE_URL = "https://threedecks.org"
DELAY_SECONDS = 5
REPO_ROOT = Path(__file__).resolve().parents[1]
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "real"
INDEX_PATH = FIXTURE_DIR / "_index.json"


@dataclass
class Fixture:
    name: str
    filename: str
    method: str = "GET"
    url: str = ""
    data: dict = field(default_factory=dict)


def ship_fixtures(ids: list[int]) -> list[Fixture]:
    return [
        Fixture(
            name=f"ship_{i}",
            filename=f"ship_{i}.html",
            url=f"{BASE_URL}/index.php?display_type=show_ship&id={i}",
        )
        for i in ids
    ]


def action_fixtures(ids: list[int]) -> list[Fixture]:
    return [
        Fixture(
            name=f"action_{i}",
            filename=f"action_{i}.html",
            url=f"{BASE_URL}/index.php?display_type=show_battle&id={i}",
        )
        for i in ids
    ]


def fleet_fixtures(ids: list[int]) -> list[Fixture]:
    return [
        Fixture(
            name=f"fleet_{i}",
            filename=f"fleet_{i}.html",
            url=f"{BASE_URL}/index.php?display_type=show_fleet&id={i}",
        )
        for i in ids
    ]


def action_index_form(page: int) -> dict:
    """The ``action_selector`` form as its "Next" button submits it: no filters."""
    return {
        "formid": "action_selector",
        "page": str(page),
        "limit": "50",
        "battle_name": "",
        "type": "0",
        "war": "0",
        "date": "",
        "date_yy": "0000",
        "date_mm": "00",
        "date_dd": "00",
    }


def actions_fleets_fixtures() -> list[Fixture]:
    """Recon fixtures for the actions and fleets crawlers (their plans in docs/plans/).

    157 Trafalgar (map coordinates, divisions), 149 2nd Cape St Vincent (no map),
    532 a single-ship action, 988 a siege; fleet 97 British, 139 Spanish.
    """
    fixtures = action_fixtures([157, 149, 532, 988])
    fixtures += fleet_fixtures([97, 139])
    fixtures += [
        Fixture(
            name="action_notfound_probe",
            filename="action_notfound_probe.html",
            url=f"{BASE_URL}/index.php?display_type=show_battle&id=999999",
        ),
        Fixture(
            name="action_index",
            filename="action_index.html",
            url=f"{BASE_URL}/index.php?display_type=select_action",
        ),
        Fixture(
            name="action_index_p2",
            filename="action_index_p2.html",
            method="POST",
            url=f"{BASE_URL}/index.php?display_type=select_action",
            data=action_index_form(2),
        ),
        Fixture(
            name="fleetlist_index",
            filename="fleetlist_index.html",
            url=f"{BASE_URL}/index.php?display_type=show_fleetlist",
        ),
        Fixture(
            name="fleet_notfound_probe",
            filename="fleet_notfound_probe.html",
            url=f"{BASE_URL}/index.php?display_type=show_fleet&id=999999",
        ),
    ]
    return fixtures


def default_fixtures() -> list[Fixture]:
    fixtures = ship_fixtures([2682, 2744, 6358])
    fixtures += [
        Fixture(
            name="notfound_probe",
            filename="notfound_probe.html",
            url=f"{BASE_URL}/index.php?display_type=show_ship&id=999999",
        ),
        Fixture(
            name="captures_es_gb",
            filename="captures_es_gb.html",
            method="POST",
            url=f"{BASE_URL}/index.php?display_type=select_capture",
            data={
                "select_from_nation": "7",
                "select_by_nation": "1",
                "select_war": "",
                "select_captures": "Change Filter",
            },
        ),
        Fixture(
            name="search_spain_p1",
            filename="search_spain_p1.html",
            method="POST",
            url=f"{BASE_URL}/index.php?display_type=ships_search",
            data={
                "show_shiplist": "1",
                "page": "1",
                "limit": "50",
                "select_nation": "7",
            },
        ),
        Fixture(
            name="search_spain_p2",
            filename="search_spain_p2.html",
            method="POST",
            url=f"{BASE_URL}/index.php?display_type=ships_search",
            data={
                "show_shiplist": "1",
                "page": "2",
                "limit": "50",
                "select_nation": "7",
            },
        ),
    ]
    fixtures += actions_fleets_fixtures()
    return fixtures


def load_index() -> dict:
    if INDEX_PATH.exists():
        return json.loads(INDEX_PATH.read_text(encoding="utf-8"))
    return {}


def save_index(index: dict) -> None:
    INDEX_PATH.parent.mkdir(parents=True, exist_ok=True)
    INDEX_PATH.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def fetch(client: httpx.Client, fixture: Fixture) -> dict:
    if fixture.method == "POST":
        response = client.post(fixture.url, data=fixture.data)
    else:
        response = client.get(fixture.url)
    body = response.content
    (FIXTURE_DIR / fixture.filename).write_bytes(body)
    return {
        "name": fixture.name,
        "url": fixture.url,
        "method": fixture.method,
        "data": fixture.data,
        "status": response.status_code,
        "bytes": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "final_url": str(response.url),
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="refetch pages already on disk")
    parser.add_argument("--only", action="append", default=[], help="fixture name(s) to fetch")
    args = parser.parse_args(argv)
    if not contact():
        print(f"error: {MISSING_CONTACT_HELP}", file=sys.stderr)
        return 2

    fixtures = default_fixtures()
    if args.only:
        wanted = set(args.only)
        fixtures = [f for f in fixtures if f.name in wanted]

    FIXTURE_DIR.mkdir(parents=True, exist_ok=True)
    index = load_index()

    pending = [
        f for f in fixtures if args.force or not (FIXTURE_DIR / f.filename).exists()
    ]
    if not pending:
        print("all fixtures present; nothing to fetch")
        return 0

    headers = {"User-Agent": build_user_agent()}
    with httpx.Client(timeout=60.0, follow_redirects=True, headers=headers) as client:
        for i, fixture in enumerate(pending):
            if i:
                time.sleep(DELAY_SECONDS)
            record = fetch(client, fixture)
            index[fixture.name] = record
            print(f"{fixture.name}: {record['status']} {record['bytes']} bytes")
    save_index(index)
    print(f"wrote {len(pending)} fixture(s) to {FIXTURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
