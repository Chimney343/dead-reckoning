"""Prize Papers portal (Goobi viewer) metadata harvest.

Saves the OpenAPI spec and the field list first, then pages the Solr index for
ships and captures. Metadata only: the terms restrict images to research,
private study or education, and robots.txt disallows ``/search/`` and ``/oai``.
Existing page files are reused so a re-run resumes where it stopped.
"""

from __future__ import annotations

import json
from pathlib import Path

from .. import core
from ..manifest import Entry
from .base import file_record, save_json

DOCSTRCTS = ("ship", "capture")
QUERIES = [
    ("ship", "DOCSTRCT:ship"),
    ("capture", "DOCSTRCT:capture"),
    ("event", "DOCTYPE:EVENT"),
]
PAGE_SIZE = 100
RESULT_FIELDS = [
    "PI",
    "PI_TOPSTRUCT",
    "IDDOC",
    "IDDOC_OWNER",
    "IDDOC_PARENT",
    "DOCSTRCT",
    "DOCTYPE",
    "MD_SHIP_*",
    "MD_CAPTURE_*",
    "MD_EVENT_*",
    "MD_EVENTDATE*",
    "MD_GEO_POINT",
    "MD_ALL_PLACE*",
    "MD_ALL_COORDS_FOR_SPATIALSEARCH",
    "MD_SHIP_FLAG_FOR_FACET",
]


def _fetch_spec(
    client,
    dest_dir: Path,
    name: str,
    url: str,
    files: dict,
    prior_files: dict,
    force: bool,
) -> None:
    path = dest_dir / name
    if path.exists() and not force:
        files[name] = {**prior_files.get(name, {}), "url": url, "skipped": True}
        return
    response = client.get(url)
    path.write_bytes(response.content)
    files[name] = file_record(path, url=str(response.url), status=response.status_code)


def _fetch_page(
    client,
    dest_dir: Path,
    name: str,
    query_url: str,
    query: str,
    offset: int,
    files: dict,
    prior_files: dict,
    force: bool,
) -> dict:
    path = dest_dir / name
    if path.exists() and not force:
        files[name] = {**prior_files.get(name, {}), "url": query_url, "skipped": True}
        return json.loads(path.read_text(encoding="utf-8"))
    response = client.post(
        query_url,
        json={
            "query": query,
            "count": PAGE_SIZE,
            "offset": offset,
            "resultFields": RESULT_FIELDS,
        },
    )
    data = response.json()
    save_json(path, data)
    files[name] = file_record(
        path,
        url=str(response.url),
        query=query,
        offset=offset,
        docs=len(data.get("docs", [])),
    )
    return data


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
    api = entry.url.rstrip("/") + "/"
    query_url = api + "index/query/"
    resolver_input = {"api": api, "docstrcts": list(DOCSTRCTS)}

    if dry_run:
        return {"files": {}, "resolver_input": resolver_input}

    dest_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}

    _fetch_spec(
        client, dest_dir, "openapi.json", api + "openapi.json", files, prior_files, force
    )
    _fetch_spec(
        client, dest_dir, "index_fields.json", api + "index/fields", files, prior_files, force
    )

    counts: dict[str, int] = {}
    pages: dict[str, int] = {}
    for docstrct, query in QUERIES:
        offset = 0
        page = 0
        total = 0
        while True:
            name = f"{docstrct}_{page:05d}.json"
            data = _fetch_page(
                client,
                dest_dir,
                name,
                query_url,
                query,
                offset,
                files,
                prior_files,
                force,
            )
            docs = data.get("docs", [])
            total = data.get("numFound", total)
            offset += len(docs)
            page += 1
            if not docs or offset >= total:
                break
        counts[docstrct] = total
        pages[docstrct] = page

    summary = {
        "counts": counts,
        "pages": pages,
        "result_fields": RESULT_FIELDS,
        "fetched_at": core.utcnow(),
    }
    save_json(dest_dir / "summary.json", summary)
    files["summary.json"] = file_record(dest_dir / "summary.json")

    resolver_input["counts"] = counts
    return {"files": files, "resolver_input": resolver_input}
