"""GitHub-hosted index.json tree: fetch the listed files under a year cap."""

from __future__ import annotations

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    index = client.get(entry.url).json()
    max_year = entry.params.get("max_year")
    base = entry.params.get("base_url") or entry.url.rsplit("/", 1)[0] + "/"

    specs: list[FileSpec] = []
    for item in index.get("years", []):
        year = item.get("year")
        filename = item.get("filename")
        if year is None or not filename:
            continue
        if max_year is not None and year > max_year:
            continue
        specs.append(
            FileSpec(
                urls=[base + filename],
                filename=safe_filename(filename),
                meta={"year": year},
            )
        )
    return specs
