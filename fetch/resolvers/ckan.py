"""CKAN package_show -> resources[], optionally filtered by format."""

from __future__ import annotations

from urllib.parse import urlparse

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    result = client.get(entry.url).json()["result"]
    wanted = entry.params.get("format")
    specs: list[FileSpec] = []
    for resource in result.get("resources", []):
        fmt = (resource.get("format") or "").upper()
        if wanted and fmt != wanted.upper():
            continue
        url = resource.get("url")
        if not url:
            continue
        filename = safe_filename(urlparse(url).path) or safe_filename(resource.get("name", ""))
        specs.append(
            FileSpec(
                urls=[url],
                filename=filename,
                meta={"package": result.get("name"), "format": fmt},
            )
        )
    if entry.filename and len(specs) == 1:
        specs[0].filename = entry.filename
    return specs
