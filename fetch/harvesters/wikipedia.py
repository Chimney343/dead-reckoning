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

REQUIRES_CONTACT = True

# MediaWiki serves at most 50 titles per query to clients without the
# apihighlimits right: longer lists are silently truncated, and the URL of a
# 400-title query is rejected outright by the edge (HTTP 431).
TITLE_BATCH = 50


def _api_json(response) -> dict:
    """Decode a MediaWiki API response, turning failures into DownloadError."""
    try:
        payload = response.json()
    except ValueError as exc:
        snippet = " ".join(response.text[:120].split())
        raise core.DownloadError(
            f"{response.status_code} from {response.url}: not JSON"
            + (f" ({snippet})" if snippet else "")
        ) from exc
    if isinstance(payload, dict) and "error" in payload:
        error = payload["error"]
        if isinstance(error, dict):
            raise core.DownloadError(
                f"{response.url}: MediaWiki error {error.get('code')}: "
                f"{error.get('info')}"
            )
        raise core.DownloadError(f"{response.url}: MediaWiki error {error}")
    return payload


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
    """Mainspace category members, following cmcontinue until exhausted.

    One categorymembers query returns at most 500 members; categories are
    routinely larger, so the continuation token must be followed or pages
    are silently missed.
    """
    titles: list[str] = []
    cmcontinue: str | None = None
    while True:
        request = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": params["category"],
            "cmlimit": "500",
            "format": "json",
            "formatversion": "2",
        }
        if cmcontinue:
            request["cmcontinue"] = cmcontinue
        payload = _api_json(client.get(api, params=request))
        members = payload.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members if m.get("ns") == 0)
        cmcontinue = (payload.get("continue") or {}).get("cmcontinue")
        if not cmcontinue:
            break
    # dict.fromkeys keeps discovery order and drops duplicates.
    return [
        t
        for t in dict.fromkeys(titles)
        if _in_period(t, params.get("min_year"), params.get("max_year"))
    ]


def resolve_titles(client, api: str, titles: list[str]) -> list[str]:
    """Resolve redirects and normalisations in batches of TITLE_BATCH.

    All titles in one request both overflow the server's 50-title cap and
    produce URLs long enough for the edge to reject (HTTP 431).
    """
    resolved: dict[int, str] = {}  # target pageid -> canonical title
    missing: list[str] = []  # nonexistent targets carry no pageid
    for start in range(0, len(titles), TITLE_BATCH):
        batch = titles[start : start + TITLE_BATCH]
        payload = _api_json(
            client.get(
                api,
                params={
                    "action": "query",
                    "titles": "|".join(batch),
                    "redirects": "1",
                    "format": "json",
                    "formatversion": "2",
                },
            )
        )
        pages = payload.get("query", {}).get("pages", {})
        if isinstance(pages, dict):  # formatversion 1 keys pages by pageid
            pages = list(pages.values())
        for page in pages:
            if "title" not in page:
                continue
            if "pageid" in page:
                # Two requested titles can redirect to the same target page.
                resolved[page["pageid"]] = page["title"]
            else:
                missing.append(page["title"])
    ordered = [title for _, title in sorted(resolved.items())]
    return ordered + missing


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
        parse = _api_json(response).get("parse", {})
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
