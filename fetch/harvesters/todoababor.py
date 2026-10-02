"""Todo a Babor: two hand-picked Spanish loss-list articles.

No licence is stated, so the manifest marks the source ``redistribute: false``.
Parsing into fate rows is a later stage; this harvester is fetch-only.
"""

from __future__ import annotations

from pathlib import Path

from ..manifest import Entry
from .base import file_record


def harvest(
    entry: Entry,
    client,
    dest_dir: Path,
    *,
    prior_files: dict | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    prior_files = prior_files or {}
    resolver_input = {"urls": entry.urls}
    if dry_run:
        return {"files": {}, "resolver_input": resolver_input}

    dest_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    for index, url in enumerate(entry.urls, start=1):
        name = f"article_{index:02d}.html"
        path = dest_dir / name
        if path.exists() and not force:
            files[name] = {**prior_files.get(name, {}), "url": url, "skipped": True}
            continue
        response = client.get(url)
        path.write_bytes(response.content)
        files[name] = file_record(
            path,
            url=url,
            final_url=str(response.url),
            status=response.status_code,
        )
    return {"files": files, "resolver_input": resolver_input}
