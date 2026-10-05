"""Source registry: the list of extractors and shared helpers (plan section 4)."""

from __future__ import annotations

from .sources import (
    das,
    emodnet,
    ibm,
    infomar,
    novascotia,
    prizepapers,
    slavevoyages,
    todoababor,
    ukho,
    wa,
    wiid,
    wikidata,
    wikipedia,
    zenodo,
)
from .types import Extract

SOURCES = [
    ukho,
    wa,
    zenodo,
    wiid,
    infomar,
    emodnet,
    novascotia,
    das,
    ibm,
    wikipedia,
    wikidata,
    slavevoyages,
    prizepapers,
    todoababor,
]

ID_TO_SOURCE = {module.ID: module for module in SOURCES}

__all__ = ["Extract", "SOURCES", "ID_TO_SOURCE"]
