"""QA report, unmapped values, unresolved places and conflicts (plan section 12)."""

from __future__ import annotations

import csv
from collections import Counter
from pathlib import Path

import pandas as pd

from .normalize import polities

LOCATION_PRECISIONS = ["surveyed", "reported", "place", "region", "none"]


def _share(series: pd.Series, predicate) -> str:
    if series.empty:
        return "0%"
    count = sum(1 for value in series if predicate(value))
    return f"{count / len(series):.0%}"


def _covered(series: pd.Series) -> str:
    if series.empty:
        return "0%"
    present = series.notna() & (series.astype(str).str.strip() != "")
    return f"{present.mean():.0%}"


def _markdown_table(frame: pd.DataFrame) -> str:
    columns = list(frame.columns)
    lines = ["| " + " | ".join(columns) + " |", "|" + "|".join(["---"] * len(columns)) + "|"]
    for row in frame.itertuples(index=False):
        lines.append("| " + " | ".join(str(value) for value in row) + " |")
    return "\n".join(lines)


def coverage_table(losses: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for source, group in losses.groupby("source", sort=True):
        row = {"source": source, "rows": len(group)}
        for precision in LOCATION_PRECISIONS:
            row[f"loc_{precision}"] = sum(
                1 for value in group["location_precision"] if value == precision
            )
        row["origin"] = _covered(group["origin_polity"])
        row["owner"] = _covered(group["owner_at_loss"])
        row["cause"] = _covered(group["cause_class"])
        row["pre_1860"] = int((pd.to_numeric(group["loss_year"], errors="coerce") <= 1860).sum())
        rows.append(row)
    return pd.DataFrame(rows)


def collect_unmapped(losses: pd.DataFrame) -> list[dict]:
    counts: Counter = Counter()
    for row in losses.to_dict("records"):
        for field in ("flag_at_loss_raw", "origin_raw"):
            raw = row.get(field)
            if not raw:
                continue
            if polities.lookup(raw) is None:
                counts[(row.get("source"), field, str(raw))] += 1
    return [
        {"source": source, "field": field, "value": value, "count": count}
        for (source, field, value), count in counts.most_common()
    ]


def collect_conflicts(losses: pd.DataFrame) -> list[dict]:
    conflicts = []
    primaries = losses[losses["is_primary"] == True]  # noqa: E712
    for cluster_id, group in losses.groupby("cluster_id", dropna=True):
        flags = {
            str(row["flag_at_loss_polity"])
            for row in group.to_dict("records")
            if row.get("flag_at_loss_polity")
        }
        if len(flags) > 1:
            conflicts.append(
                {
                    "cluster_id": cluster_id,
                    "ship_name": next(
                        (n for n in group["ship_name"] if n), ""
                    ),
                    "flags": "|".join(sorted(flags)),
                    "sources": "|".join(sorted(set(group["source"]))),
                }
            )
    _ = primaries
    return conflicts


def unresolved_rows(unresolved: dict[str, int]) -> list[dict]:
    return [
        {"location_text": text, "count": count}
        for text, count in sorted(unresolved.items(), key=lambda item: -item[1])
    ]


def write_reports(
    losses: pd.DataFrame,
    events: pd.DataFrame,
    output_dir: Path,
    unresolved: dict[str, int],
    *,
    build_date: str,
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    table = coverage_table(losses)
    unmapped = collect_unmapped(losses)
    conflicts = collect_conflicts(losses)

    with (output_dir / "unmapped_values.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["source", "field", "value", "count"])
        writer.writeheader()
        writer.writerows(unmapped)
    with (output_dir / "unresolved_places.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["location_text", "count"])
        writer.writeheader()
        writer.writerows(unresolved_rows(unresolved))
    with (output_dir / "conflicts.csv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=["cluster_id", "ship_name", "flags", "sources"]
        )
        writer.writeheader()
        writer.writerows(conflicts)

    cluster_count = int(losses["cluster_id"].nunique()) if "cluster_id" in losses else 0
    lines = [
        "# Ship-losses QA report",
        "",
        f"Built: {build_date}",
        "",
        "## Coverage per source",
        "",
        _markdown_table(table) if not table.empty else "(no rows)",
        "",
        "## Totals",
        "",
        f"- Loss rows: {len(losses)}",
        f"- Ownership events: {len(events)}",
        f"- Clusters: {cluster_count}",
        f"- Unresolved place phrases: {len(unresolved)} distinct",
        f"- Unmapped raw values: {len(unmapped)} distinct",
        f"- Flag conflicts: {len(conflicts)} clusters",
        "",
        "## 50 most frequent unresolved place phrases",
        "",
    ]
    for item in unresolved_rows(unresolved)[:50]:
        lines.append(f"- {item['location_text']} ({item['count']})")
    lines += ["", "## Licensing", ""]
    for source, group in losses.groupby("source", sort=True):
        licence = group["licence"].iloc[0] if not group.empty else "unknown"
        red = bool(group["redistribute"].iloc[0]) if not group.empty else False
        lines.append(f"- {source}: {licence} (redistribute={red})")
    report = output_dir / "qa_report.md"
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return report


def finding(losses: pd.DataFrame) -> dict:
    """A short data-driven headline for the map title."""
    usable = losses[losses["is_total_loss"] == True]  # noqa: E712
    years = pd.to_numeric(usable["loss_year"], errors="coerce").dropna()
    window = usable[pd.to_numeric(usable["loss_year"], errors="coerce").between(1500, 1860)]
    cause_counts = window["cause_class"].value_counts()
    origin_counts = window["flag_at_loss_polity"].value_counts()
    return {
        "rows": int(len(window)),
        "start": int(years.min()) if not years.empty else 1500,
        "end": int(years.max()) if not years.empty else 1860,
        "sources": int(losses["source"].nunique()),
        "top_cause": cause_counts.index[0] if not cause_counts.empty else "unknown",
        "top_cause_share": (
            f"{cause_counts.iloc[0] / cause_counts.sum():.0%}" if not cause_counts.empty else "0%"
        ),
        "top_flag": origin_counts.index[0] if not origin_counts.empty else "unknown",
    }
