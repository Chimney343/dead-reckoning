"""Zenodo REST: /api/records/{id} -> files[]."""

from __future__ import annotations

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename


def resolve(entry: Entry, client) -> list[FileSpec]:
    data = client.get(entry.url).json()
    record = data.get("id") or entry.params.get("record")
    version = (data.get("metadata") or {}).get("version")
    specs: list[FileSpec] = []
    for item in data.get("files", []):
        key = item.get("key") or item.get("filename") or ""
        links = item.get("links", {})
        url = links.get("content") or links.get("download") or links.get("self")
        if not url:
            continue
        specs.append(
            FileSpec(
                urls=[url],
                filename=safe_filename(key),
                meta={"record": record, "version": version, "key": key},
            )
        )
    return specs
