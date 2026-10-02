"""Harvesters for sources that need more than a file URL."""

from __future__ import annotations

from . import prizepapers, todoababor, wikidata, wikipedia

HARVESTERS = {
    "prizepapers": prizepapers.harvest,
    "wikidata": wikidata.harvest,
    "wikipedia": wikipedia.harvest,
    "todoababor": todoababor.harvest,
}
