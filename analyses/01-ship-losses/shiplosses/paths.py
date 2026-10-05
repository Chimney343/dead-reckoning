"""Filesystem locations for the ship-losses analysis."""

from __future__ import annotations

from pathlib import Path

PACKAGE = Path(__file__).resolve().parent
ANALYSIS = PACKAGE.parent
REPO = ANALYSIS.parents[1]
DATA_RAW = REPO / "data" / "raw"
DATA = ANALYSIS / "data"
OUTPUTS = ANALYSIS / "outputs"
ASSETS = ANALYSIS / "assets"
