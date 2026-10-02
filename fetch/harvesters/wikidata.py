"""Wikidata: SPARQL item lists plus full entity JSON.

Writes ``p11085.csv`` (the join key shared with the Three Decks agent) and a
``summary.json`` with the counts the research note asked for. Requires
DR_CONTACT for the Wikimedia User-Agent policy.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .. import core
from ..manifest import Entry
from .base import file_record, save_json

SPARQL_ENDPOINT = "https://query.wikidata.org/sparql"
ENTITY_ENDPOINT = "https://www.wikidata.org/w/api.php"
BATCH = 50

P11085_QUERY = """\
SELECT ?item ?id ?itemLabel WHERE {
  ?item wdt:P11085 ?id .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es". }
}
"""

SPAIN_SHIPS_QUERY = """\
SELECT DISTINCT ?item ?itemLabel WHERE {
  ?item wdt:P31/wdt:P279* wd:Q170472 .
  { ?item wdt:P17 wd:Q29 } UNION
  { ?item wdt:P8047 wd:Q29 } UNION
  { ?item wdt:P137 wd:Q1651855 } UNION
  { ?item wdt:P17 wd:Q204920 } .
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es". }
}
LIMIT 5000
"""

BATTLES_QUERY = """\
SELECT ?item ?itemLabel ?date ?coord WHERE {
  ?item wdt:P31/wdt:P279* wd:Q178561 .
  OPTIONAL { ?item wdt:P585 ?date. }
  OPTIONAL { ?item wdt:P625 ?coord. }
  FILTER NOT EXISTS { ?item wdt:P585 ?d. FILTER(YEAR(?d) < 1492 || YEAR(?d) > 1860) }
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en,es". }
}
LIMIT 20000
"""

QUERIES = [
    ("p11085", P11085_QUERY),
    ("spain_ships", SPAIN_SHIPS_QUERY),
    ("naval_battles", BATTLES_QUERY),
]


def _qid(value: str) -> str:
    return value.rsplit("/", 1)[-1] if "/" in value else value


def _sparql(
    client,
    endpoint: str,
    query: str,
    name: str,
    dest_dir: Path,
    files: dict,
    prior_files: dict,
    force: bool,
) -> list[dict]:
    filename = f"sparql_{name}.json"
    path = dest_dir / filename
    if path.exists() and not force:
        files[filename] = {**prior_files.get(filename, {}), "skipped": True, "query_name": name}
        data = json.loads(path.read_text(encoding="utf-8"))["result"]
    else:
        response = client.get(endpoint, params={"query": query, "format": "json"})
        data = response.json()
        save_json(path, {"query": query, "result": data})
        files[filename] = file_record(path, url=str(response.url), query_name=name)
    return data.get("results", {}).get("bindings", [])


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
    endpoint = entry.url or SPARQL_ENDPOINT
    resolver_input = {"queries": [name for name, _ in QUERIES]}

    if dry_run:
        resolver_input["endpoint"] = endpoint
        return {"files": {}, "resolver_input": resolver_input}

    dest_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, dict] = {}
    qids: set[str] = set()
    p11085_rows: list[tuple[str, str, str]] = []

    for name, query in QUERIES:
        bindings = _sparql(
            client, endpoint, query, name, dest_dir, files, prior_files, force
        )
        for binding in bindings:
            qid = _qid(binding.get("item", {}).get("value", ""))
            if qid.startswith("Q"):
                qids.add(qid)
            if name == "p11085":
                p11085_rows.append(
                    (
                        qid,
                        binding.get("id", {}).get("value", ""),
                        binding.get("itemLabel", {}).get("value", ""),
                    )
                )

    csv_path = dest_dir / "p11085.csv"
    with open(csv_path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["qid", "threedecks_id", "label"])
        writer.writerows(p11085_rows)
    files["p11085.csv"] = file_record(csv_path, rows=len(p11085_rows))

    ordered = sorted(qids)
    entity_files = 0
    for offset in range(0, len(ordered), BATCH):
        batch = ordered[offset : offset + BATCH]
        filename = f"entities_{offset // BATCH:05d}.json"
        path = dest_dir / filename
        if path.exists() and not force:
            files[filename] = {**prior_files.get(filename, {}), "skipped": True, "ids": batch}
            entity_files += 1
            continue
        response = client.get(
            ENTITY_ENDPOINT,
            params={
                "action": "wbgetentities",
                "ids": "|".join(batch),
                "format": "json",
                "maxlag": "5",
            },
        )
        save_json(path, response.json())
        files[filename] = file_record(path, url=str(response.url), ids=batch)
        entity_files += 1

    summary = {
        "p11085_count": len(p11085_rows),
        "qids": len(ordered),
        "entity_files": entity_files,
        "queries": [name for name, _ in QUERIES],
        "fetched_at": core.utcnow(),
    }
    save_json(dest_dir / "summary.json", summary)
    files["summary.json"] = file_record(dest_dir / "summary.json")

    resolver_input.update({"p11085_count": len(p11085_rows), "qids": len(ordered)})
    return {"files": files, "resolver_input": resolver_input}
