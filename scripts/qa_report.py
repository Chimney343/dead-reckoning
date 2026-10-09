"""Post-crawl data-quality report (Plan 6, layer 8).

    uv run python scripts/qa_report.py [--data-dir data/threedecks] [--out report.md]

Reports counts per nation, the share with a Launched date, unknown labels and
unknown sections by frequency, incarnation symmetry, capture/incarnation date mismatches and
frontier rows stuck in error states. Source disagreements are reported, never
reconciled here (Plan 3.4).
"""

from __future__ import annotations

import argparse
import json
import re
from collections import Counter
from pathlib import Path

from threedecks.state import StateStore

# A value shaped like a date (optional qualifier, digits, dots and slashes).
DATE_SHAPED = re.compile(r"^(?:bef\.?|aft\.?|c\.)?\s*\d[\d./]*$", re.IGNORECASE)

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def build_report(data_dir: Path) -> tuple[dict, str]:
    store = StateStore(data_dir / "state.sqlite")
    try:
        ships = list(store.iter_ships())
        captures = list(store.iter_captures())
        actions = list(store.iter_actions())
        action_index = list(store.iter_action_index())
        fleets = list(store.iter_fleets())
        fleet_index = list(store.iter_fleet_index())
        counts = store.counts_by_status()
        action_index_counts = store.page_counts_by_status("action_index")
        action_counts = store.page_counts_by_status("action")
        fleet_index_counts = store.page_counts_by_status("fleet_index")
        fleet_counts = store.page_counts_by_status("fleet")
    finally:
        store.close()

    by_nation = Counter(s.get("nation_name") or "unknown" for s in ships)
    with_launch = sum(
        1
        for s in ships
        if any(item.get("label") == "Launched" for item in s.get("lifecycle", []))
    )
    unknown_labels = Counter(
        label for s in ships for label in s.get("unknown_labels", [])
    )
    unknown_sections = Counter(
        section for s in ships for section in s.get("unknown_sections", [])
    )

    # Incarnation symmetry: "A Becomes B" implies "B Previously A", and the reverse.
    # A link to a ship not fetched yet is unchecked, not broken.
    by_id = {ship.get("td_id"): ship for ship in ships}
    broken: list[dict] = []
    unchecked = 0
    pairs = (("next_td_ids", "previous_td_ids"), ("previous_td_ids", "next_td_ids"))
    for ship in ships:
        td_id = ship.get("td_id")
        for field, mirror in pairs:
            for other_id in ship.get(field, []):
                other = by_id.get(other_id)
                if other is None:
                    unchecked += 1
                elif td_id not in other.get(mirror, []):
                    broken.append({"from": td_id, "to": other_id, "field": field})

    # Capture rows whose captured ship has no Captured-type lifecycle row.
    captured_ids = {c.get("captured_td_id") for c in captures if c.get("captured_td_id")}
    by_id = {s.get("td_id"): s for s in ships}
    missing_capture_lifecycle = [
        td_id
        for td_id in sorted(captured_ids)
        if td_id in by_id
        and not any(
            item.get("label") == "Captured" for item in by_id[td_id].get("lifecycle", [])
        )
    ]

    stuck = {
        status: count
        for status, count in counts.items()
        if status in {"error", "parse_error"} and count
    }

    actions_report = build_actions_report(
        ships, actions, action_index, action_index_counts, action_counts
    )

    fleets_report = build_fleets_report(
        ships, fleets, fleet_index, fleet_index_counts, fleet_counts
    )

    report = {
        "unparseable_dates": unparseable_dates(ships),
        "ships": len(ships),
        "captures": len(captures),
        "by_nation": dict(by_nation.most_common()),
        "with_launched_date": with_launch,
        "unknown_labels": dict(unknown_labels.most_common(50)),
        "unknown_sections": dict(unknown_sections.most_common()),
        "broken_incarnation_links": broken,
        "unchecked_incarnation_links": unchecked,
        "captures_missing_lifecycle": missing_capture_lifecycle,
        "frontier_errors": stuck,
        "actions": actions_report,
        "fleets": fleets_report,
    }
    return report, render_markdown(report)


def build_actions_report(ships, actions, action_index, index_counts, action_counts) -> dict:
    """Data-quality signals for the actions crawl (actions plan 3.4, A8)."""
    action_by_id = {a.get("battle_id"): a for a in actions}
    index_ids = {row.get("battle_id") for row in action_index if row.get("battle_id")}

    history: dict[int, set] = {}
    for ship in ships:
        for event in ship.get("history", []):
            for battle_id in event.get("battle_ids", []):
                history.setdefault(battle_id, set()).add(ship.get("td_id"))

    ship_history_not_in_action: list[dict] = []
    for battle_id, ship_ids in history.items():
        action = action_by_id.get(battle_id)
        if action is None:
            continue
        participants = {
            p.get("td_id")
            for p in action.get("participants", [])
            if p.get("td_id") is not None
        }
        for ship_id in sorted(ship_ids):
            if ship_id not in participants:
                ship_history_not_in_action.append(
                    {"ship_id": ship_id, "battle_id": battle_id}
                )

    by_id = {s.get("td_id"): s for s in ships}
    action_not_in_ship_history: list[dict] = []
    participants_without_td_id = participants_not_in_ships = 0
    for action in actions:
        battle_id = action.get("battle_id")
        for participant in action.get("participants", []):
            td_id = participant.get("td_id")
            if td_id is None:
                participants_without_td_id += 1
                continue
            if td_id not in by_id:
                participants_not_in_ships += 1
                continue
            linked = {
                b
                for event in by_id[td_id].get("history", [])
                for b in event.get("battle_ids", [])
            }
            if battle_id not in linked:
                action_not_in_ship_history.append({"battle_id": battle_id, "td_id": td_id})

    date_mismatches: list[dict] = []
    for ship in ships:
        for event in ship.get("history", []):
            history_date = (event.get("date") or {}).get("iso")
            for battle_id in event.get("battle_ids", []):
                action = action_by_id.get(battle_id)
                if action is None:
                    continue
                action_date = (action.get("date") or {}).get("iso")
                if history_date and action_date and history_date != action_date:
                    date_mismatches.append(
                        {
                            "ship_id": ship.get("td_id"),
                            "battle_id": battle_id,
                            "history_date": history_date,
                            "action_date": action_date,
                        }
                    )

    with_coordinates = sum(
        1
        for a in actions
        if a.get("latitude") is not None and a.get("longitude") is not None
    )
    unknown_rows = Counter(row for a in actions for row in a.get("unknown_rows", []))
    unknown_action_sections = Counter(
        section for a in actions for section in a.get("unknown_sections", [])
    )
    action_frontier_errors = {
        status: count
        for status, count in {**index_counts, **action_counts}.items()
        if status in {"error", "parse_error"} and count
    }

    return {
        "count": len(actions),
        "index_rows": len(action_index),
        "index_only_ids": sorted(index_ids - set(action_by_id)),
        "fetched_missing_from_index": sorted(set(action_by_id) - index_ids),
        "history_battles_without_action": sorted(
            b for b in history if b not in action_by_id
        ),
        "ship_history_not_in_action": ship_history_not_in_action,
        "action_not_in_ship_history": action_not_in_ship_history,
        "date_mismatches": date_mismatches,
        "participants_without_td_id": participants_without_td_id,
        "participants_not_in_ships": participants_not_in_ships,
        "with_coordinates": with_coordinates,
        "coordinate_share": (with_coordinates / len(actions)) if actions else 0.0,
        "unknown_rows": dict(unknown_rows.most_common(50)),
        "unknown_sections": dict(unknown_action_sections.most_common()),
        "frontier_errors": action_frontier_errors,
    }


def build_fleets_report(ships, fleets, fleet_index, index_counts, fleet_counts) -> dict:
    """Data-quality signals for the fleets crawl (fleets plan 3.4)."""
    fleet_by_id = {f.get("fleet_id"): f for f in fleets}
    index_ids = {row.get("fleet_id") for row in fleet_index if row.get("fleet_id")}
    ships_by_id = {s.get("td_id"): s for s in ships}

    # Symmetry with ship records: ship X cites fleet F but F's ships lack X.
    ship_fleet_not_in_fleet: list[dict] = []
    for ship in ships:
        for fleet_row in ship.get("fleets", []):
            fleet_id = fleet_row.get("fleet_id")
            if fleet_id is None or fleet_id not in fleet_by_id:
                continue
            members = {s.get("td_id") for s in fleet_by_id[fleet_id].get("ships", [])}
            if ship.get("td_id") not in members:
                ship_fleet_not_in_fleet.append(
                    {"ship_id": ship.get("td_id"), "fleet_id": fleet_id}
                )

    # The reverse: fleet F lists ship X but X's fleets lack F; plus ship checks.
    fleet_ship_not_in_ship_fleets: list[dict] = []
    ships_without_td_id = ships_not_in_ships = 0
    out_of_lifecycle: list[dict] = []
    for fleet in fleets:
        fleet_id = fleet.get("fleet_id")
        for member in fleet.get("ships", []):
            td_id = member.get("td_id")
            if td_id is None:
                ships_without_td_id += 1
                continue
            ship = ships_by_id.get(td_id)
            if ship is None:
                ships_not_in_ships += 1
                continue
            cited = {row.get("fleet_id") for row in ship.get("fleets", [])}
            if fleet_id not in cited:
                fleet_ship_not_in_ship_fleets.append({"fleet_id": fleet_id, "ship_id": td_id})
            launched, last = _lifecycle_bounds(ship)
            for field in ("joined", "left"):
                iso = (member.get(field) or {}).get("iso")
                if iso and ((launched and iso < launched) or (last and iso > last)):
                    out_of_lifecycle.append(
                        {"fleet_id": fleet_id, "td_id": td_id, "field": field, "date": iso}
                    )

    unknown_labels = Counter(label for f in fleets for label in f.get("unknown_labels", []))
    unknown_sections = Counter(
        section for f in fleets for section in f.get("unknown_sections", [])
    )
    frontier_errors = {
        status: count
        for status, count in {**index_counts, **fleet_counts}.items()
        if status in {"error", "parse_error"} and count
    }

    return {
        "count": len(fleets),
        "index_rows": len(fleet_index),
        "index_only_ids": sorted(index_ids - set(fleet_by_id)),
        "fetched_missing_from_index": sorted(set(fleet_by_id) - index_ids),
        "ship_fleet_not_in_fleet": ship_fleet_not_in_fleet,
        "fleet_ship_not_in_ship_fleets": fleet_ship_not_in_ship_fleets,
        "ships_without_td_id": ships_without_td_id,
        "ships_not_in_ships": ships_not_in_ships,
        "out_of_lifecycle": out_of_lifecycle,
        "unknown_labels": dict(unknown_labels.most_common(50)),
        "unknown_sections": dict(unknown_sections.most_common()),
        "frontier_errors": frontier_errors,
    }


def _lifecycle_bounds(ship: dict) -> tuple[str | None, str | None]:
    """A ship's (Launched, last lifecycle) ISO dates, from its lifecycle rows."""
    dates = [
        (item.get("label"), (item.get("date") or {}).get("iso"))
        for item in ship.get("lifecycle", [])
    ]
    launched = next((iso for label, iso in dates if label == "Launched" and iso), None)
    others = [iso for _label, iso in dates if iso]
    return launched, (max(others) if others else None)


def unparseable_dates(ships: list[dict]) -> list[dict]:
    """Date-shaped values the parser could not read, e.g. ``60.1739`` or
    ``36.5.1801``: errors in the source, kept raw and listed for the owner."""
    found = []
    for ship in ships:
        for row in ship.get("base_rows", []):
            text = (row.get("text") or "").strip()
            if row.get("date") is None and DATE_SHAPED.match(text):
                found.append({"td_id": ship["td_id"], "where": row["label"], "raw": text})
        for event in ship.get("history", []):
            date = event.get("date") or {}
            raw = (date.get("raw") or "").strip()
            if raw and not date.get("precision"):
                found.append({"td_id": ship["td_id"], "where": "Service History", "raw": raw})
    return found


def render_markdown(report: dict) -> str:
    lines = [
        "# Three Decks QA report",
        "",
        f"- ships: {report['ships']}",
        f"- captures: {report['captures']}",
        f"- ships with a Launched date: {report['with_launched_date']}",
        "",
        "## Nations",
        "",
    ]
    lines += [f"- {nation}: {n}" for nation, n in report["by_nation"].items()]
    lines += ["", "## Unknown base labels", ""]
    if report["unknown_labels"]:
        lines += [f"- {label}: {n}" for label, n in report["unknown_labels"].items()]
    else:
        lines.append("- none")
    lines += ["", "## Unknown sections", ""]
    if report["unknown_sections"]:
        lines += [f"- {section}: {n}" for section, n in report["unknown_sections"].items()]
    else:
        lines.append("- none")
    lines += [
        "",
        "## Broken incarnation links",
        "",
        f"- {len(report['broken_incarnation_links'])} not mirrored",
        f"- {report['unchecked_incarnation_links']} to ships not fetched yet",
        "",
        "## Captures with no Captured lifecycle row",
        "",
        f"- {len(report['captures_missing_lifecycle'])}",
        "",
        "## Frontier errors",
        "",
    ]
    lines += [f"- {status}: {n}" for status, n in report["frontier_errors"].items()] or ["- none"]
    actions = report["actions"]
    lines += [
        "",
        "## Actions",
        "",
        f"- actions stored: {actions['count']}",
        f"- index rows: {actions['index_rows']}",
        f"- index ids not fetched: {len(actions['index_only_ids'])}",
        f"- fetched ids missing from the index: {len(actions['fetched_missing_from_index'])}",
        f"- history battles with no action record: "
        f"{len(actions['history_battles_without_action'])}",
        f"- ship-history battles not listing the ship: "
        f"{len(actions['ship_history_not_in_action'])}",
        f"- action participants not in the ship's history: "
        f"{len(actions['action_not_in_ship_history'])}",
        f"- action/history date mismatches: {len(actions['date_mismatches'])}",
        f"- participants with no td_id: {actions['participants_without_td_id']}",
        f"- participants not found in ships: {actions['participants_not_in_ships']}",
        f"- actions with coordinates: {actions['with_coordinates']} "
        f"({actions['coordinate_share']:.0%})",
        f"- unknown rows: {sum(actions['unknown_rows'].values())}",
        f"- unknown sections: {sum(actions['unknown_sections'].values())}",
    ]
    lines += [
        f"- frontier errors ({kind}): {n}"
        for kind, n in actions["frontier_errors"].items()
    ] or ["- frontier errors: none"]
    fleets = report["fleets"]
    lines += [
        "",
        "## Fleets",
        "",
        f"- fleets stored: {fleets['count']}",
        f"- index rows: {fleets['index_rows']}",
        f"- index ids not fetched: {len(fleets['index_only_ids'])}",
        f"- fetched ids missing from the index: {len(fleets['fetched_missing_from_index'])}",
        f"- ship fleets not listing the ship: {len(fleets['ship_fleet_not_in_fleet'])}",
        f"- fleet ships not in the ship's fleets: "
        f"{len(fleets['fleet_ship_not_in_ship_fleets'])}",
        f"- fleet ships with no td_id: {fleets['ships_without_td_id']}",
        f"- fleet ships not found in ships: {fleets['ships_not_in_ships']}",
        f"- fleet ships outside the ship's lifecycle: {len(fleets['out_of_lifecycle'])}",
        f"- unknown labels: {sum(fleets['unknown_labels'].values())}",
        f"- unknown sections: {sum(fleets['unknown_sections'].values())}",
    ]
    lines += [
        f"- frontier errors ({kind}): {n}"
        for kind, n in fleets["frontier_errors"].items()
    ] or ["- frontier errors: none"]
    bad = report["unparseable_dates"]
    lines += ["", "## Unparseable dates (errors in the source; worth sending to the owner)", ""]
    lines += [f"- ship {d['td_id']}, {d['where']}: {d['raw']}" for d in bad[:100]] or ["- none"]
    if len(bad) > 100:
        lines.append(f"- ... and {len(bad) - 100} more")
    lines.append("")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", default=str(DEFAULT_DATA_DIR))
    parser.add_argument("--out", default=None)
    args = parser.parse_args(argv)

    report, markdown = build_report(Path(args.data_dir))
    print(markdown)
    if args.out:
        Path(args.out).write_text(markdown, encoding="utf-8")
        (Path(args.out).with_suffix(".json")).write_text(
            json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
