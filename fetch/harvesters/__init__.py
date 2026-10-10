"""Harvesters for sources that need more than a file URL."""

from __future__ import annotations

from . import prizepapers, todoababor, wikidata, wikipedia

_MODULES = {
    "prizepapers": prizepapers,
    "wikidata": wikidata,
    "wikipedia": wikipedia,
    "todoababor": todoababor,
}

HARVESTERS = {name: module.harvest for name, module in _MODULES.items()}


def requires_contact(resolver: str) -> bool:
    """True when the harvester for ``resolver`` refuses to run without a contact."""
    module = _MODULES.get(resolver)
    return module is not None and bool(getattr(module, "REQUIRES_CONTACT", False))
