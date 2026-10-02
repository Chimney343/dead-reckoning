"""Socrata: rows.csv plus the view metadata JSON."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..core import FileSpec
from ..manifest import Entry

VIEW_RE = re.compile(r"/api/views/([^/]+)/")


def resolve(entry: Entry, client) -> list[FileSpec]:
    url = entry.url
    match = VIEW_RE.search(url)
    view = match.group(1) if match else entry.params.get("view", entry.id)
    parsed = urlparse(url)
    meta_url = f"{parsed.scheme}://{parsed.netloc}/api/views/{view}.json"
    csv_name = entry.filename or "rows.csv"
    return [
        FileSpec(urls=[url], filename=csv_name, meta={"view": view, "kind": "data"}),
        FileSpec(urls=[meta_url], filename=f"{view}.json", meta={"view": view, "kind": "metadata"}),
    ]
