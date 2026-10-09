"""Export the state database to JSONL and Parquet (Plan 6).

    uv run python scripts/export.py [--data-dir data/threedecks] [--out DIR]

``ships.jsonl`` and ``captures.jsonl`` are the lossless exports (one record per
line); the Parquet files carry a flattened, scalar view for analysis.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from threedecks.state import StateStore

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def flatten_ship(record: dict) -> dict:
    dates = {
        item.get("label"): (item.get("date") or {}).get("iso")
        for item in record.get("lifecycle", [])
    }
    return {
        "td_id": record.get("td_id"),
        "name": record.get("name"),
        "nation_id": record.get("nation_id"),
        "nation_name": record.get("nation_name"),
        "operator": record.get("operator"),
        "nominal_guns": record.get("nominal_guns"),
        "category": record.get("category"),
        "ship_type": record.get("ship_type"),
        "ship_type_id": record.get("ship_type_id"),
        "rig": record.get("rig"),
        "how_acquired": record.get("how_acquired"),
        "class_id": record.get("class_id"),
        "class_name": record.get("class_name"),
        "launched": dates.get("Launched"),
        "captured": dates.get("Captured"),
        "sold": dates.get("Sold"),
        "history_count": len(record.get("history", [])),
        "source_count": len(record.get("sources", [])),
        "url": record.get("url"),
        "fetched_at": record.get("fetched_at"),
        "content_sha256": record.get("content_sha256"),
        "parser_version": record.get("parser_version"),
    }


def flatten_capture(row: dict) -> dict:
    return {
        "captured_td_id": row.get("captured_td_id"),
        "captured_label": row.get("captured_label"),
        "date_raw": row.get("date", {}).get("raw"),
        "date_iso": row.get("date", {}).get("iso"),
        "captor_td_ids": ",".join(str(i) for i in row.get("captor_td_ids", [])),
        "place_text": row.get("place_text"),
        "from_nation_id": row.get("from_nation_id"),
        "by_nation_id": row.get("by_nation_id"),
        "war_id": row.get("war_id"),
    }


def _date_field(date: dict | None, field: str):
    return (date or {}).get(field)


def flatten_action(record: dict, index_by_id: dict[int, dict]) -> dict:
    date = record.get("date")
    end_date = record.get("end_date")
    index_row = index_by_id.get(record.get("battle_id")) or {}
    return {
        "battle_id": record.get("battle_id"),
        "name": record.get("name"),
        "action_type": index_row.get("action_type"),
        "date_iso": _date_field(date, "iso"),
        "date_gregorian": _date_field(date, "gregorian_iso"),
        "end_date_iso": _date_field(end_date, "iso"),
        "end_date_gregorian": _date_field(end_date, "gregorian_iso"),
        "war_id": record.get("war_id"),
        "place_ids": ",".join(str(link.get("id")) for link in record.get("places", [])),
        "latitude": record.get("latitude"),
        "longitude": record.get("longitude"),
        "previous_battle_id": record.get("previous_battle_id"),
        "next_battle_id": record.get("next_battle_id"),
        "side_count": len(record.get("sides", [])),
        "participant_count": len(record.get("participants", [])),
        "url": record.get("url"),
        "fetched_at": record.get("fetched_at"),
        "content_sha256": record.get("content_sha256"),
        "parser_version": record.get("parser_version"),
    }


def flatten_participants(record: dict) -> list[dict]:
    sides = record.get("sides", [])
    divisions = record.get("divisions", [])
    rows: list[dict] = []
    for participant in record.get("participants", []):
        side_index = participant.get("side_index")
        division_index = participant.get("division_index")
        side = (
            sides[side_index]
            if isinstance(side_index, int) and 0 <= side_index < len(sides)
            else {}
        )
        division = (
            divisions[division_index]
            if isinstance(division_index, int) and 0 <= division_index < len(divisions)
            else {}
        )
        ship = participant.get("ship") or {}
        rows.append(
            {
                "battle_id": record.get("battle_id"),
                "side_index": side_index,
                "side_label": side.get("label"),
                "side_nation_ids": ",".join(str(i) for i in side.get("nation_ids", [])),
                "division_label": division.get("label"),
                "td_id": participant.get("td_id"),
                "ship_label": participant.get("ship_label"),
                "ship_tooltip": " | ".join(ship.get("tooltip", [])),
                "commander_ids": ",".join(str(i) for i in participant.get("commander_ids", [])),
                "notes": participant.get("notes"),
                "flags": ",".join(participant.get("flags", [])),
            }
        )
    return rows


def flatten_fleet(record: dict, index_by_id: dict[int, dict]) -> dict:
    index_row = index_by_id.get(record.get("fleet_id")) or {}
    return {
        "fleet_id": record.get("fleet_id"),
        "name": record.get("name"),
        "nation_id": index_row.get("nation_id"),
        "commander_ids": ",".join(str(i) for i in record.get("commander_ids", [])),
        "formed_iso": _date_field(record.get("formed"), "iso"),
        "disbanded_iso": _date_field(record.get("disbanded"), "iso"),
        "ship_count": len(record.get("ships", [])),
        "event_count": len(record.get("events", [])),
        "url": record.get("url"),
        "fetched_at": record.get("fetched_at"),
        "content_sha256": record.get("content_sha256"),
        "parser_version": record.get("parser_version"),
    }


def flatten_fleet_ships(record: dict) -> list[dict]:
    rows: list[dict] = []
    for ship in record.get("ships", []):
        link = ship.get("ship") or {}
        rows.append(
            {
                "fleet_id": record.get("fleet_id"),
                "td_id": ship.get("td_id"),
                "ship_label": ship.get("ship_label"),
                "ship_tooltip": " | ".join(link.get("tooltip", [])),
                "joined_iso": _date_field(ship.get("joined"), "iso"),
                "left_iso": _date_field(ship.get("left"), "iso"),
                "commander_ids": ",".join(str(i) for i in ship.get("commander_ids", [])),
                "notes": ship.get("notes"),
            }
        )
    return rows


def flatten_fleet_events(record: dict) -> list[dict]:
    rows: list[dict] = []
    for event in record.get("events", []):
        date = event.get("date") or {}
        rows.append(
            {
                "fleet_id": record.get("fleet_id"),
                "date_raw": date.get("raw"),
                "date_iso": date.get("iso"),
                "text": event.get("text"),
                "ship_ids": ",".join(str(i) for i in event.get("ship_ids", [])),
                "place_ids": ",".join(str(i) for i in event.get("place_ids", [])),
                "battle_ids": ",".join(str(i) for i in event.get("battle_ids", [])),
                "source_code": event.get("source_code"),
            }
        )
    return rows


def write_jsonl(path: Path, records) -> int:
    count = 0
    with path.open("w", encoding="utf-8") as handle:
        for record in records:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
            count += 1
    return count


def write_parquet(path: Path, rows: list[dict]) -> bool:
    try:
        import pandas as pd
    except ImportError:  # pragma: no cover
        return False
    pd.DataFrame(rows).to_parquet(path, index=False)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    data_dir = Path(args.data_dir)
    out_dir = Path(args.out) if args.out else data_dir / "exports"
    out_dir.mkdir(parents=True, exist_ok=True)

    store = StateStore(data_dir / "state.sqlite")
    try:
        ships = list(store.iter_ships())
        captures = list(store.iter_captures())
        actions = list(store.iter_actions())
        action_index = list(store.iter_action_index())
        fleets = list(store.iter_fleets())
        fleet_index = list(store.iter_fleet_index())
    finally:
        store.close()

    write_jsonl(out_dir / "ships.jsonl", ships)
    write_jsonl(out_dir / "captures.jsonl", captures)
    write_jsonl(out_dir / "actions.jsonl", actions)
    write_jsonl(out_dir / "action_index.jsonl", action_index)
    write_jsonl(out_dir / "fleets.jsonl", fleets)
    write_jsonl(out_dir / "fleet_index.jsonl", fleet_index)
    parquet = write_parquet(out_dir / "ships.parquet", [flatten_ship(s) for s in ships])
    write_parquet(out_dir / "captures.parquet", [flatten_capture(c) for c in captures])
    index_by_id = {row.get("battle_id"): row for row in action_index}
    write_parquet(
        out_dir / "actions.parquet",
        [flatten_action(record, index_by_id) for record in actions],
    )
    participant_rows = [row for record in actions for row in flatten_participants(record)]
    write_parquet(out_dir / "action_participants.parquet", participant_rows)
    fleet_index_by_id = {row.get("fleet_id"): row for row in fleet_index}
    write_parquet(
        out_dir / "fleets.parquet",
        [flatten_fleet(record, fleet_index_by_id) for record in fleets],
    )
    fleet_ship_rows = [row for record in fleets for row in flatten_fleet_ships(record)]
    write_parquet(out_dir / "fleet_ships.parquet", fleet_ship_rows)
    fleet_event_rows = [row for record in fleets for row in flatten_fleet_events(record)]
    write_parquet(out_dir / "fleet_events.parquet", fleet_event_rows)
    print(
        f"exported {len(ships)} ships, {len(captures)} captures, {len(actions)} actions and "
        f"{len(fleets)} fleets to {out_dir}"
        + ("" if parquet else " (Parquet skipped: pandas/pyarrow unavailable)")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
