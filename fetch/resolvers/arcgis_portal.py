"""ArcGIS Online / Portal: item data downloads via content/items/{id}/data."""

from __future__ import annotations

import re

from ..core import FileSpec
from ..manifest import Entry

ITEM_RE = re.compile(r"/items/([^/]+)/")


def resolve(entry: Entry, client) -> list[FileSpec]:
    specs: list[FileSpec] = []
    for url in entry.urls:
        match = ITEM_RE.search(url)
        item = match.group(1) if match else None
        if entry.filename and len(entry.urls) == 1:
            filename = entry.filename
        elif item:
            filename = f"{item}.bin"
        else:
            filename = f"{entry.id}.bin"
        specs.append(FileSpec(urls=[url], filename=filename, meta={"item": item}))
    return specs
