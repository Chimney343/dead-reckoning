"""Static Equal Earth small multiples (plan section 7)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from .interactive import CAUSE_COLORS

PERIODS = [
    ("1500-1699", 1500, 1699),
    ("1700-1763", 1700, 1763),
    ("1764-1815", 1764, 1815),
    ("1816-1860", 1816, 1860),
]
EQUAL_EARTH = "EPSG:8857"


def _land(raw_root: Path):
    archive = raw_root / "naturalearth" / "ne_50m_land.zip"
    if not archive.exists():
        return None
    try:
        import geopandas as gpd
    except ImportError:
        return None
    land = gpd.read_file(f"zip://{archive}")
    return land.to_crs(EQUAL_EARTH)


def build(losses: pd.DataFrame, output_dir: Path, raw_root: Path) -> list[Path]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    land = _land(raw_root)
    if land is None:
        return []
    try:
        import geopandas as gpd
    except ImportError:
        return []

    primaries = losses[
        (losses["is_primary"] == True)  # noqa: E712
        & (losses["is_total_loss"] == True)  # noqa: E712
        & losses["lat"].notna()
        & losses["lon"].notna()
    ].copy()
    if primaries.empty:
        return []
    points = gpd.GeoDataFrame(
        primaries,
        geometry=gpd.points_from_xy(primaries["lon"], primaries["lat"]),
        crs="EPSG:4326",
    ).to_crs(EQUAL_EARTH)
    points["plot_x"] = points.geometry.x
    points["plot_y"] = points.geometry.y

    output_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for label, start, end in PERIODS:
        subset = points[
            pd.to_numeric(points["loss_year"], errors="coerce").between(start, end)
        ]
        figure, axes = plt.subplots(figsize=(13.333, 7), dpi=150)
        land.plot(ax=axes, color="#E6E6E6", edgecolor="none")
        for cause, colour in CAUSE_COLORS.items():
            group = subset[subset["cause_class"] == cause]
            if group.empty:
                continue
            axes.scatter(group["plot_x"], group["plot_y"], s=4, c=colour, label=cause, linewidths=0)
        axes.set_title(f"Ship losses, {label}")
        axes.set_axis_off()
        path = output_dir / f"map_{label}.png"
        figure.savefig(path, bbox_inches="tight", facecolor="white")
        plt.close(figure)
        written.append(path)
    return written
