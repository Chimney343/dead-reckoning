"""Plain URL(s), no discovery."""

from __future__ import annotations

from urllib.parse import urlparse

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    specs: list[FileSpec] = []
    for url in entry.urls:
        if entry.filename and len(entry.urls) == 1:
            filename = entry.filename
        else:
            filename = safe_filename(urlparse(url).path) or entry.filename or entry.id
        specs.append(FileSpec(urls=[url], filename=filename, meta={"url": url}))
    return specs
