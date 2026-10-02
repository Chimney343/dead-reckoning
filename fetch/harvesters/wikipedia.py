"""Wikipedia: fetch parsed HTML, wikitext and revision ids.

The harvester is fetch-only. Parsing tables into rows belongs to the next
stage. It refuses to run without DR_CONTACT because Wikimedia's User-Agent
policy requires a contact address.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from .. import core
from ..manifest import Entry
from .base import file_record, safe_stem, save_json


def _title_years(title: str) -> set[int]:
    return {int(y) for y in re.findall(r"(\d{4})s?", title)}


def _in_period(title: str, min_year: int | None, max_year: int | None) -> bool:
    years = _title_years(title)
    if not years:
        return False
    for year in years:
        if min_year is not None and year + 9 < min_year:
            continue
        if max_year is not None and year > max_year:
            continue
        return True
    return False


def discover_titles(client, api: str, params: dict) -> list[str]:
    response = client.get(
        api,
        params={
            "action": "query",
            "list": "categorymembers",
            "cmtitle": params["category"],
            "cmlimit": "500",
            "format": "json",
            "formatversion": "2",
        },
    )
    members = response.json().get("query", {}).get("categorymembers", [])
    titles = [m["title"] for m in members if m.get("ns") == 0]
    return [
        t
        for t in titles
        if _in_period(t, params.get("min_year"), params.get("max_year"))
    ]


def resolve_titles(client, api: str, titles: list[str]) -> list[str]:
    if not titles:
        return []
    response = client.get(
        api,
        params={
            "action": "query",
            "titles": "|".join(titles),
            "redirects": "1",
            "format": "json",
            "formatversion": "2",
        },
    )
    pages = response.json().get("query", {}).get("pages", {})
    if isinstance(pages, dict):
        ordered = sorted(pages.values(), key=lambda p: p.get("pageid", 0))
        return [p["title"] for p in ordered if "title" in p]
    return [p["title"] for p in pages if "title" in p]


def harvest(
    entry: Entry,
    client,
    dest_dir: Path,
    *,
    prior_files: dict | None = None,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    core.require_contact(client.contact)
    prior_files = prior_files or {}
    api = entry.url
    wiki = entry.params.get("wiki", "en")
    titles = entry.params.get("titles")
    if titles is None and entry.params.get("category"):
        titles = discover_titles(client, api, entry.params)
    titles = list(titles or [])

    resolver_input = {"wiki": wiki, "titles": titles, "revids": {}}
    if dry_run:
        return {"files": {}, "resolver_input": resolver_input}

    if titles:
        titles = resolve_titles(client, api, titles)
    dest_dir.mkdir(parents=True, exist_ok=True)

    files: dict[str, dict] = {}
    for title in titles:
        name = f"{safe_stem(title)}.json"
        path = dest_dir / name
        if path.exists() and not force:
            payload = json.loads(path.read_text(encoding="utf-8"))
            files[name] = {
                **prior_files.get(name, {}),
                "url": payload.get("url"),
                "skipped": True,
                "title": payload.get("title"),
                "revid": payload.get("revid"),
            }
            resolver_input["revids"][title] = payload.get("revid")
            continue
        response = client.get(
            api,
            params={
                "action": "parse",
                "page": title,
                "prop": "text|wikitext|revid",
                "format": "json",
                "formatversion": "2",
                "redirects": "1",
            },
        )
        parse = response.json().get("parse", {})
        payload = {
            "title": parse.get("title", title),
            "revid": parse.get("revid"),
            "wikitext": parse.get("wikitext"),
            "html": parse.get("text"),
            "url": str(response.url),
            "wiki": wiki,
            "fetched_at": core.utcnow(),
        }
        save_json(dest_dir / name, payload)
        files[name] = file_record(
            dest_dir / name,
            url=str(response.url),
            title=payload["title"],
            revid=payload["revid"],
        )
        resolver_input["revids"][title] = payload["revid"]
    return {"files": files, "resolver_input": resolver_input}
