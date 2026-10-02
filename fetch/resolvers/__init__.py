"""Resolve a manifest entry into concrete download targets."""

from __future__ import annotations

from pathlib import PurePosixPath

from ..core import FileSpec
from ..manifest import Entry


class ResolverError(ValueError):
    """No resolver is registered for an entry, or resolution failed."""


def safe_filename(name: str) -> str:
    """Reduce a possibly nested name to a flat, Windows-safe filename."""
    name = (name or "").replace("\\", "/")
    base = PurePosixPath(name).name
    for char in '<>:"|?*':
        base = base.replace(char, "_")
    return base.strip() or "download.bin"


# Imported after safe_filename so submodules can do ``from . import safe_filename``.
from . import (  # noqa: E402
    arcgis_portal,
    arcgis_rest,
    ckan,
    dataverse,
    direct,
    figshare,
    github,
    github_index,
    socrata,
    zenodo,
)

RESOLVERS = {
    "direct": direct.resolve,
    "zenodo": zenodo.resolve,
    "dataverse": dataverse.resolve,
    "figshare": figshare.resolve,
    "ckan": ckan.resolve,
    "github": github.resolve,
    "github_index": github_index.resolve,
    "socrata": socrata.resolve,
    "arcgis_portal": arcgis_portal.resolve,
    "arcgis_rest": arcgis_rest.resolve,
}


def resolve(entry: Entry, client) -> list[FileSpec]:
    try:
        resolver = RESOLVERS[entry.resolver]
    except KeyError as exc:
        raise ResolverError(f"unknown resolver {entry.resolver!r} for {entry.id}") from exc
    return resolver(entry, client)
