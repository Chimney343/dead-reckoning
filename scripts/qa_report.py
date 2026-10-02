"""Post-crawl data-quality report (Plan 6, layer 8).

    uv run python scripts/qa_report.py [--data-dir data/threedecks] [--out report.md]

Reports counts per nation, the share with a Launched date, unknown labels by
frequency, incarnation symmetry, capture/incarnation date mismatches and
frontier rows stuck in error states. Source disagreements are reported, never
reconciled here (Plan 3.4).
"""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

from threedecks.state import StateStore

DEFAULT_DATA_DIR = Path(__file__).resolve().parents[1] / "data" / "threedecks"


def build_report(data_dir: Path) -> tuple[dict, str]:
    store = StateStore(data_dir / "state.sqlite")
    try:
        ships = list(store.iter_ships())
        captures = list(store.iter_captures())
        counts = store.counts_by_status()
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

    # Incarnation symmetry: A -> B implies B -> A.
    edges: dict[int, set[int]] = defaultdict(set)
    for ship in ships:
        td_id = ship.get("td_id")
        for nxt in ship.get("next_td_ids", []):
            edges[td_id].add(nxt)
    broken = [
        {"from": a, "to": b}
        for a, targets in edges.items()
        for b in targets
        if a not in edges.get(b, set())
    ]

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

    report = {
        "ships": len(ships),
        "captures": len(captures),
        "by_nation": dict(by_nation.most_common()),
        "with_launched_date": with_launch,
        "unknown_labels": dict(unknown_labels.most_common(50)),
        "broken_incarnation_links": broken,
        "captures_missing_lifecycle": missing_capture_lifecycle,
        "frontier_errors": stuck,
    }
    return report, render_markdown(report)


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
    lines += [
        "",
        "## Broken incarnation links",
        "",
        f"- {len(report['broken_incarnation_links'])} not mirrored",
        "",
        "## Captures with no Captured lifecycle row",
        "",
        f"- {len(report['captures_missing_lifecycle'])}",
        "",
        "## Frontier errors",
        "",
    ]
    lines += [f"- {status}: {n}" for status, n in report["frontier_errors"].items()] or ["- none"]
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
