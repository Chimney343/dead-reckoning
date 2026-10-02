"""figshare API v2: /v2/articles/{id} -> files[].download_url."""

from __future__ import annotations

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    data = client.get(entry.url).json()
    article = data.get("id") or entry.params.get("article")
    specs: list[FileSpec] = []
    for item in data.get("files", []):
        url = item.get("download_url")
        if not url:
            continue
        specs.append(
            FileSpec(
                urls=[url],
                filename=safe_filename(item.get("name", "")),
                meta={"article": article, "file_id": item.get("id")},
            )
        )
    return specs
