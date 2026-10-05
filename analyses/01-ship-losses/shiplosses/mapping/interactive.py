"""Interactive Leaflet map build (plan section 7).

The data is inlined compactly: strings are pooled in ``STRS`` and enums are
integer indices, so a 120k-feature build stays inside the size budget.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .. import qa

CAUSE_ORDER = [
    "stranded",
    "foundered",
    "weather",
    "fire_explosion",
    "collision",
    "enemy_action",
    "scuttled",
    "unknown",
]
CAUSE_COLORS = {
    "stranded": "#88CCEE",
    "foundered": "#332288",
    "weather": "#44AA99",
    "fire_explosion": "#CC6677",
    "collision": "#DDCC77",
    "enemy_action": "#882255",
    "scuttled": "#117733",
    "unknown": "#888888",
}
PRECISIONS = ["surveyed", "reported", "place", "region", "none"]
CAUSE_INDEX = {name: index for index, name in enumerate(CAUSE_ORDER)}
PREC_INDEX = {name: index for index, name in enumerate(PRECISIONS)}
PALETTE = list(CAUSE_COLORS.values())
OTHER = "#888888"
MIN_YEAR, MAX_YEAR = 1400, 2030
DEFAULT_MIN, DEFAULT_MAX = 1500, 1860
MAX_TEXT = 200

TEMPLATE = Path(__file__).with_name("template.html")


def _text(value: object) -> str:
    return value if isinstance(value, str) else ""


def _list(value: object) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value] if value else []
    try:
        return [str(item) for item in value if isinstance(item, str) and item]
    except TypeError:
        return []


class _Pools:
    def __init__(self) -> None:
        self.strings = [""]
        self.index = {"": 0}

    def sid(self, value: object) -> int:
        text = _text(value)
        if len(text) > MAX_TEXT:
            text = text[: MAX_TEXT - 1] + "\u2026"
        key = text[:MAX_TEXT]
        found = self.index.get(key)
        if found is None:
            found = len(self.strings)
            self.index[key] = found
            self.strings.append(key)
        return found


def polity_colors(losses: pd.DataFrame) -> dict[str, str]:
    window = losses[losses["is_total_loss"] == True]  # noqa: E712
    years = pd.to_numeric(window["loss_year"], errors="coerce")
    window = window[years.between(DEFAULT_MIN, DEFAULT_MAX)]
    counts = window["flag_at_loss_polity"].dropna().value_counts()
    colors = {}
    for position, polity in enumerate(counts.index[:7]):
        colors[str(polity)] = PALETTE[position % len(PALETTE)]
    colors.setdefault("Other", OTHER)
    return colors


def _membership(losses: pd.DataFrame, source_index: dict[str, int]) -> dict[int, list]:
    multi: dict[int, list] = {}
    group_column = "cluster_id" if "cluster_id" in losses.columns else None
    if group_column:
        for _, group in losses.groupby(group_column, dropna=True):
            if len(group) < 2:
                continue
            primaries = group[group["is_primary"] == True]  # noqa: E712
            if primaries.empty:
                continue
            anchor = int(primaries.index[0])
            multi[anchor] = [
                [source_index.get(_text(row.get("source")), 0), _text(row.get("source_record_id"))]
                for row in group.to_dict("records")
            ]
    return multi


def build(
    losses: pd.DataFrame,
    output: Path,
    *,
    build_date: str,
    redistributable_only: bool = False,
) -> Path:
    if redistributable_only:
        losses = losses[losses["redistribute"] == True]  # noqa: E712
    primaries = losses[
        (losses["is_primary"] == True)  # noqa: E712
        & (losses["is_total_loss"] == True)  # noqa: E712
        & losses["lat"].notna()
        & losses["lon"].notna()
    ].copy()

    sources = sorted({_text(value) for value in losses["source"]})
    source_index = {name: index for index, name in enumerate(sources)}
    source_table = []
    for name in sources:
        group = losses[losses["source"] == name]
        source_table.append(
            {"n": name, "u": _text(group["source_url"].iloc[0]) if not group.empty else ""}
        )

    pools = _Pools()
    features: list[list] = []
    for _, row in primaries.iterrows():
        precision = _text(row.get("location_precision")) or "none"
        cause = _text(row.get("cause_class")) or "unknown"
        former = _list(row.get("former_names"))
        location = _text(row.get("location_text"))
        if row.get("geocode_method") == "source_coords":
            location = ""
        year = row.get("loss_year")
        year = int(year) if pd.notna(year) else 0
        changed = 1 if row.get("ownership_changed") is True else 0
        features.append(
            [
                pools.sid(row.get("ship_name") or "(unnamed)"),
                year,
                round(float(row["lat"]), 4),
                round(float(row["lon"]), 4),
                PREC_INDEX.get(precision, 4),
                CAUSE_INDEX.get(cause, 7),
                pools.sid(row.get("flag_at_loss_polity")),
                pools.sid(row.get("origin_polity")),
                changed,
                pools.sid(location),
                pools.sid(row.get("cause_raw")),
                pools.sid(row.get("owner_at_loss")),
                pools.sid(row.get("ownership_change")),
                pools.sid("|".join(former)),
                source_index.get(_text(row.get("source")), 0),
                pools.sid(row.get("source_record_id")),
                1,
                int(row.name),
            ]
        )
    features.sort(key=lambda f: (f[1], f[0], f[2], f[3]))

    members = _membership(losses, source_index)

    info = qa.finding(losses)
    if info["rows"]:
        title = (
            f"{info['top_cause'].replace('_', ' ').title()} losses dominate the "
            f"Age of Sail record ({info['top_cause_share']} of {info['rows']} plotted)"
        )
    else:
        title = "No ship losses in the current dataset"
    subtitle = (
        f"{info['rows']} ship losses, {info['start']}\u2013{info['end']}, "
        f"from {info['sources']} sources"
    )

    source_rows = []
    for source, group in losses.groupby("source", sort=True):
        licence = group["licence"].iloc[0] if not group.empty else "unknown"
        source_rows.append(f"{source} ({licence})")
    sources_html = "Sources: " + ", ".join(source_rows)

    template = TEMPLATE.read_text(encoding="utf-8")
    html = (
        template.replace("__TITLE__", title)
        .replace("__SUBTITLE__", subtitle)
        .replace("__BUILD__", build_date)
        .replace("__SOURCES_HTML__", sources_html)
        .replace("__CAUSE_ORDER_JSON__", json.dumps(CAUSE_ORDER))
        .replace("__CAUSE_COLORS_JSON__", json.dumps(CAUSE_COLORS))
        .replace("__PREC_JSON__", json.dumps(PRECISIONS))
        .replace("__STRS_JSON__", json.dumps(pools.strings, ensure_ascii=False))
        .replace("__SRC_JSON__", json.dumps(source_table, ensure_ascii=False))
        .replace("__MEMBERS_JSON__", json.dumps(members, separators=(",", ":")))
        .replace("__POLITY_COLORS_JSON__", json.dumps(polity_colors(losses)))
        .replace("__RAW_JSON__", json.dumps(features, separators=(",", ":")))
        .replace("__MIN_YEAR__", str(MIN_YEAR))
        .replace("__MAX_YEAR__", str(MAX_YEAR))
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output
