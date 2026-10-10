"""Harvester tests. All API responses are mocked; no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from fetch import core, harvesters
from fetch.manifest import Entry


def make_entry(**kwargs) -> Entry:
    base = dict(
        id="x",
        group="captures",
        title="t",
        resolver="todoababor",
        licence="None stated",
        tier="T2",
        status="verified",
    )
    base.update(kwargs)
    return Entry(**base)


def read(path: Path):
    return path.read_text(encoding="utf-8")


# --- contact requirements -------------------------------------------------


def test_requires_contact_only_for_contact_harvesters():
    assert harvesters.requires_contact("wikipedia") is True
    assert harvesters.requires_contact("wikidata") is True
    assert harvesters.requires_contact("prizepapers") is False
    assert harvesters.requires_contact("todoababor") is False
    assert harvesters.requires_contact("direct") is False


# --- todoababor -----------------------------------------------------------


@respx.mock
def test_todoababor_saves_each_page(tmp_path):
    entry = make_entry(
        resolver="todoababor",
        urls=["https://www.todoababor.es/a/", "https://www.todoababor.es/b/"],
    )
    respx.get("https://www.todoababor.es/a/").mock(
        return_value=httpx.Response(200, text="<html>A</html>")
    )
    respx.get("https://www.todoababor.es/b/").mock(
        return_value=httpx.Response(200, text="<html>B</html>")
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = harvesters.HARVESTERS["todoababor"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert (tmp_path / "article_01.html").read_text() == "<html>A</html>"
    assert (tmp_path / "article_02.html").read_text() == "<html>B</html>"
    assert set(result["files"]) == {"article_01.html", "article_02.html"}


# --- wikipedia ------------------------------------------------------------


def _wiki_responder(request: httpx.Request) -> httpx.Response:
    params = request.url.params
    action = params.get("action")
    if action == "query" and params.get("titles"):
        requested = params["titles"].split("|")
        pages = {
            str(i + 1): {"pageid": i + 1, "title": title}
            for i, title in enumerate(requested)
        }
        return httpx.Response(
            200,
            json={"query": {"normalized": [], "pages": pages}},
        )
    if action == "query" and params.get("list") == "categorymembers":
        return httpx.Response(
            200,
            json={
                "query": {
                    "categorymembers": [
                        {"pageid": 1, "ns": 0, "title": "List of shipwrecks in 1797"},
                        {"pageid": 2, "ns": 0, "title": "List of shipwrecks in the 1700s"},
                        {"pageid": 3, "ns": 0, "title": "List of shipwrecks in 1900"},
                    ]
                }
            },
        )
    if action == "parse":
        title = params.get("page") or "T"
        return httpx.Response(
            200,
            json={
                "parse": {
                    "title": title,
                    "revid": 12345,
                    "wikitext": f"== {title} ==",
                    "text": f"<p>{title}</p>",
                }
            },
        )
    return httpx.Response(400, json={"error": "unexpected", "params": dict(params)})


def _wiki_client():
    return core.HttpClient(contact="me@example.org", backoff_base=0.0)


@respx.mock
def test_wikipedia_requires_contact(tmp_path):
    entry = make_entry(resolver="wikipedia", url="https://en.wikipedia.org/w/api.php",
                       params={"wiki": "en", "titles": ["List of naval battles"]})
    with core.HttpClient(contact=None, backoff_base=0.0) as client:
        with pytest.raises(core.MissingContactError):
            harvesters.HARVESTERS["wikipedia"](
                entry, client, tmp_path, prior_files={}, force=False, dry_run=False
            )


@respx.mock
def test_wikipedia_parses_titles_and_records_revid(tmp_path):
    respx.get(url__startswith="https://en.wikipedia.org/w/api.php").mock(
        side_effect=_wiki_responder
    )
    entry = make_entry(
        resolver="wikipedia",
        url="https://en.wikipedia.org/w/api.php",
        params={"wiki": "en", "titles": ["List of naval battles"]},
    )
    with _wiki_client() as client:
        result = harvesters.HARVESTERS["wikipedia"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    name = "List_of_naval_battles.json"
    data = json.loads(read(tmp_path / name))
    assert data["revid"] == 12345
    assert data["wikitext"] == "== List of naval battles =="
    assert data["html"] == "<p>List of naval battles</p>"
    assert result["resolver_input"]["revids"]["List of naval battles"] == 12345


@respx.mock
def test_wikipedia_discovers_shipwreck_titles_by_year(tmp_path):
    respx.get(url__startswith="https://en.wikipedia.org/w/api.php").mock(
        side_effect=_wiki_responder
    )
    entry = make_entry(
        resolver="wikipedia",
        url="https://en.wikipedia.org/w/api.php",
        params={
            "wiki": "en",
            "category": "Category:Lists of shipwrecks by year",
            "min_year": 1650,
            "max_year": 1860,
        },
    )
    with _wiki_client() as client:
        harvesters.HARVESTERS["wikipedia"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert (tmp_path / "List_of_shipwrecks_in_1797.json").exists()
    assert (tmp_path / "List_of_shipwrecks_in_the_1700s.json").exists()
    assert not (tmp_path / "List_of_shipwrecks_in_1900.json").exists()


# --- wikidata -------------------------------------------------------------


def _sparql_responder(request: httpx.Request) -> httpx.Response:
    query = request.url.params.get("query", "")
    if "P11085" in query:
        bindings = [
            {
                "item": {"value": "http://www.wikidata.org/entity/Q1"},
                "id": {"value": "100"},
                "itemLabel": {"value": "Ship One"},
            },
            {
                "item": {"value": "http://www.wikidata.org/entity/Q2"},
                "id": {"value": "200"},
                "itemLabel": {"value": "Ship Two"},
            },
        ]
    else:
        bindings = []
    return httpx.Response(200, json={"head": {"vars": ["item"]}, "results": {"bindings": bindings}})


@respx.mock
def test_wikidata_writes_p11085_join_key_and_entities(tmp_path):
    respx.get("https://query.wikidata.org/sparql").mock(side_effect=_sparql_responder)
    respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(
            200,
            json={"entities": {"Q1": {"id": "Q1"}, "Q2": {"id": "Q2"}}},
        )
    )
    entry = make_entry(
        resolver="wikidata", url="https://query.wikidata.org/sparql"
    )
    with core.HttpClient(contact="me@example.org", backoff_base=0.0) as client:
        result = harvesters.HARVESTERS["wikidata"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    csv_text = read(tmp_path / "p11085.csv")
    assert "qid,threedecks_id,label" in csv_text
    assert "Q1,100,Ship One" in csv_text
    assert (tmp_path / "summary.json").exists()
    assert result["resolver_input"]["p11085_count"] == 2
    assert any(name.startswith("entities_") for name in result["files"])


# --- prizepapers ----------------------------------------------------------


def _pp_responder(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    query = body.get("query", "")
    num = 2 if "ship" in query else 1
    count = num if body.get("count") else 0
    docs = [{"IDDOC": f"{query}-{i}", "PI": f"PPN{i}"} for i in range(count)]
    return httpx.Response(200, json={"docs": docs, "numFound": num})


@respx.mock
def test_prizepapers_saves_spec_fields_and_pages(tmp_path):
    respx.get("https://portal.prizepapers.de/api/v1/openapi.json").mock(
        return_value=httpx.Response(200, json={"openapi": "3.0", "paths": {}})
    )
    respx.get("https://portal.prizepapers.de/api/v1/index/fields").mock(
        return_value=httpx.Response(200, json=[{"field": "MD_SHIP_FLAG"}])
    )
    respx.post(url__startswith="https://portal.prizepapers.de/api/v1/index/query").mock(
        side_effect=_pp_responder
    )
    entry = make_entry(
        resolver="prizepapers", url="https://portal.prizepapers.de/api/v1/"
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = harvesters.HARVESTERS["prizepapers"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert (tmp_path / "openapi.json").exists()
    assert (tmp_path / "index_fields.json").exists()
    assert (tmp_path / "ship_00000.json").exists()
    assert (tmp_path / "capture_00000.json").exists()
    assert result["resolver_input"]["counts"]["ship"] == 2


@respx.mock
def test_prizepapers_harvests_event_pages(tmp_path):
    respx.get("https://portal.prizepapers.de/api/v1/openapi.json").mock(
        return_value=httpx.Response(200, json={"openapi": "3.0", "paths": {}})
    )
    respx.get("https://portal.prizepapers.de/api/v1/index/fields").mock(
        return_value=httpx.Response(200, json=[{"field": "PI_TOPSTRUCT"}])
    )
    sent: list[dict] = []

    def responder(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        sent.append(body)
        query = body.get("query", "")
        num = 1 if ("DOCTYPE:EVENT" in query or "capture" in query) else 2
        docs = [{"PI": f"{query}-{i}", "DOCTYPE": "EVENT", "PI_TOPSTRUCT": "PPN1",
                 "MD_EVENT_CAPTURE_LINK": "PPN9"} for i in range(num)]
        return httpx.Response(200, json={"docs": docs, "numFound": num})

    respx.post(url__startswith="https://portal.prizepapers.de/api/v1/index/query").mock(
        side_effect=responder
    )
    entry = make_entry(
        resolver="prizepapers", url="https://portal.prizepapers.de/api/v1/"
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = harvesters.HARVESTERS["prizepapers"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert (tmp_path / "event_00000.json").exists()
    assert result["resolver_input"]["counts"]["event"] == 1
    event_fields = next(body["resultFields"] for body in sent if "DOCTYPE:EVENT" in body["query"])
    assert "PI_TOPSTRUCT" in event_fields
    assert "MD_EVENTDATE*" in event_fields
    assert "DOCTYPE" in event_fields


@respx.mock
def test_prizepapers_second_run_makes_no_request(tmp_path):
    respx.get("https://portal.prizepapers.de/api/v1/openapi.json").mock(
        return_value=httpx.Response(200, json={"openapi": "3.0"})
    )
    respx.get("https://portal.prizepapers.de/api/v1/index/fields").mock(
        return_value=httpx.Response(200, json=[{"field": "MD_SHIP_FLAG"}])
    )
    route = respx.post(
        url__startswith="https://portal.prizepapers.de/api/v1/index/query"
    ).mock(side_effect=_pp_responder)
    entry = make_entry(resolver="prizepapers", url="https://portal.prizepapers.de/api/v1/")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        harvesters.HARVESTERS["prizepapers"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
        assert route.call_count == 3
        harvesters.HARVESTERS["prizepapers"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert route.call_count == 3


@respx.mock
def test_wikidata_second_run_makes_no_request(tmp_path):
    route = respx.get("https://query.wikidata.org/sparql").mock(side_effect=_sparql_responder)
    entity_route = respx.get(url__startswith="https://www.wikidata.org/w/api.php").mock(
        return_value=httpx.Response(
            200, json={"entities": {"Q1": {"id": "Q1"}, "Q2": {"id": "Q2"}}}
        )
    )
    entry = make_entry(resolver="wikidata", url="https://query.wikidata.org/sparql")
    with core.HttpClient(contact="me@example.org", backoff_base=0.0) as client:
        harvesters.HARVESTERS["wikidata"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
        assert route.call_count == 3
        assert entity_route.call_count == 1
        harvesters.HARVESTERS["wikidata"](
            entry, client, tmp_path, prior_files={}, force=False, dry_run=False
        )
    assert route.call_count == 3
    assert entity_route.call_count == 1
