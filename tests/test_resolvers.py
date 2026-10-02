"""Resolver tests. All responses are mock fixtures; no network."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
import respx

from fetch import core, resolvers
from fetch.manifest import Entry

FIXTURES = Path(__file__).parent / "fixtures"


def fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def make_entry(**kwargs) -> Entry:
    base = dict(
        id="x",
        group="wrecks",
        title="t",
        resolver="direct",
        licence="CC-BY-4.0",
        tier="T1",
        status="verified",
    )
    base.update(kwargs)
    return Entry(**base)


@pytest.fixture
def client():
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as c:
        yield c


# --- direct ---------------------------------------------------------------


def test_direct_single_url(client):
    entry = make_entry(url="https://example.org/path/data.csv", resolver="direct")
    specs = resolvers.resolve(entry, client)
    assert len(specs) == 1
    assert specs[0].urls == ["https://example.org/path/data.csv"]
    assert specs[0].filename == "data.csv"


def test_direct_filename_override(client):
    entry = make_entry(url="https://example.org/x", filename="wiid.csv", resolver="direct")
    assert resolvers.resolve(entry, client)[0].filename == "wiid.csv"


def test_direct_multiple_urls(client):
    entry = make_entry(
        urls=["https://example.org/a.csv", "https://example.org/b.pdf"],
        resolver="direct",
    )
    specs = resolvers.resolve(entry, client)
    assert [s.filename for s in specs] == ["a.csv", "b.pdf"]


# --- zenodo ---------------------------------------------------------------


@respx.mock
def test_zenodo_resolves_files_using_key(client):
    respx.get("https://zenodo.org/api/records/7347768").mock(
        return_value=httpx.Response(200, json=fixture("zenodo_record.json"))
    )
    entry = make_entry(url="https://zenodo.org/api/records/7347768", resolver="zenodo")
    specs = resolvers.resolve(entry, client)
    assert len(specs) == 1
    assert specs[0].filename == "shipWrecks.csv"
    assert specs[0].urls == [
        "https://zenodo.org/api/records/7347768/files/shipWrecks.csv/content"
    ]
    assert specs[0].meta["record"] == 7347768


@respx.mock
def test_zenodo_flattens_nested_key(client):
    respx.get("https://zenodo.org/api/records/13749501").mock(
        return_value=httpx.Response(200, json=fixture("zenodo_record_nested.json"))
    )
    entry = make_entry(url="https://zenodo.org/api/records/13749501", resolver="zenodo")
    specs = resolvers.resolve(entry, client)
    assert specs[0].filename == "toflit18_data-1.0.2.zip"
    assert specs[0].meta["version"] == "1.0.2"


# --- dataverse ------------------------------------------------------------


@respx.mock
def test_dataverse_builds_access_urls(client):
    url = "https://dataverse.harvard.edu/api/datasets/:persistentId?persistentId=doi:10.7910/DVN/UXDJLQ"
    respx.get(url).mock(return_value=httpx.Response(200, json=fixture("dataverse_dataset.json")))
    entry = make_entry(url=url, resolver="dataverse")
    specs = resolvers.resolve(entry, client)
    assert [s.filename for s in specs] == ["puertos-metadata.txt", "puertos.zip"]
    assert specs[1].urls == ["https://dataverse.harvard.edu/api/access/datafile/3385667"]
    assert specs[0].meta["doi"] == "doi:10.7910/DVN/UXDJLQ"
    assert specs[0].meta["version"] == 1


# --- figshare -------------------------------------------------------------


@respx.mock
def test_figshare_uses_download_url(client):
    url = "https://api.figshare.com/v2/articles/27176202"
    respx.get(url).mock(return_value=httpx.Response(200, json=fixture("figshare_article.json")))
    entry = make_entry(url=url, resolver="figshare")
    specs = resolvers.resolve(entry, client)
    assert [s.filename for s in specs] == ["cargoes_measurement.csv", "shipmaster.csv"]
    assert specs[0].urls == ["https://ndownloader.figshare.com/files/49710771"]
    assert specs[0].meta["article"] == 27176202


# --- ckan -----------------------------------------------------------------


@respx.mock
def test_ckan_filters_by_format(client):
    url = "https://example.org/api/3/action/package_show?id=wrecks"
    respx.get(url).mock(return_value=httpx.Response(200, json=fixture("ckan_package.json")))
    entry = make_entry(url=url, resolver="ckan", params={"format": "CSV"})
    specs = resolvers.resolve(entry, client)
    assert len(specs) == 1
    assert specs[0].urls == ["https://example.org/wrecks.csv"]


@respx.mock
def test_ckan_without_format_filter_returns_all(client):
    url = "https://example.org/api/3/action/package_show?id=wrecks"
    respx.get(url).mock(return_value=httpx.Response(200, json=fixture("ckan_package.json")))
    entry = make_entry(url=url, resolver="ckan")
    assert len(resolvers.resolve(entry, client)) == 2


# --- github ---------------------------------------------------------------


def test_github_builds_codeload_archive(client):
    entry = make_entry(url="https://github.com/jrnold/CDB90", resolver="github")
    specs = resolvers.resolve(entry, client)
    assert specs[0].urls == ["https://codeload.github.com/jrnold/CDB90/zip/HEAD"]
    assert specs[0].filename == "CDB90-HEAD.zip"
    assert specs[0].meta["repo"] == "jrnold/CDB90"


def test_github_passes_through_raw_url(client):
    url = "https://github.com/Seshat-Global-History-Databank/cliopatria/raw/main/cliopatria.geojson.zip"
    entry = make_entry(url=url, resolver="github")
    specs = resolvers.resolve(entry, client)
    assert specs[0].urls == [url]
    assert specs[0].filename == "cliopatria.geojson.zip"


@respx.mock
def test_github_index_filters_by_year(client):
    url = "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/index.json"
    respx.get(url).mock(
        return_value=httpx.Response(
            200,
            json={
                "years": [
                    {"year": 1492, "filename": "world_1492.geojson"},
                    {"year": 1880, "filename": "world_1880.geojson"},
                    {"year": 1900, "filename": "world_1900.geojson"},
                ]
            },
        )
    )
    entry = make_entry(url=url, resolver="github_index", params={"max_year": 1880})
    specs = resolvers.resolve(entry, client)
    assert [s.filename for s in specs] == ["world_1492.geojson", "world_1880.geojson"]
    assert specs[0].urls == [
        "https://raw.githubusercontent.com/aourednik/historical-basemaps/master/world_1492.geojson"
    ]
    assert specs[0].meta["year"] == 1492


# --- socrata --------------------------------------------------------------


@respx.mock
def test_socrata_returns_csv_and_metadata(client):
    url = "https://data.novascotia.ca/api/views/rq3a-h5hk/rows.csv?accessType=DOWNLOAD"
    respx.get("https://data.novascotia.ca/api/views/rq3a-h5hk.json").mock(
        return_value=httpx.Response(200, json=fixture("socrata_view.json"))
    )
    entry = make_entry(url=url, filename="novascotia.csv", resolver="socrata")
    specs = resolvers.resolve(entry, client)
    assert [s.filename for s in specs] == ["novascotia.csv", "rq3a-h5hk.json"]
    assert specs[0].urls == [url]


# --- arcgis_portal --------------------------------------------------------


def test_arcgis_portal_item_data(client):
    item = "1aa31582b285461f81518007eeed9963"
    url = f"https://datahub.admiralty.co.uk/portal/sharing/rest/content/items/{item}/data"
    entry = make_entry(url=url, resolver="arcgis_portal", filename="ukho.xlsx")
    specs = resolvers.resolve(entry, client)
    assert specs[0].urls == [url]
    assert specs[0].filename == "ukho.xlsx"
    assert specs[0].meta["item"] == item


# --- arcgis_rest ----------------------------------------------------------


@respx.mock
def test_arcgis_rest_pages_are_count_driven(client):
    base = "https://example.org/rest/services/wrecks/MapServer/0/query"
    respx.get(url__startswith=base).mock(
        return_value=httpx.Response(200, json=fixture("arcgis_rest_count.json"))
    )
    entry = make_entry(
        url=base,
        resolver="arcgis_rest",
        filename="wa.geojson",
        params={"where": "1=1", "out_fields": "*", "page_size": 200},
    )
    specs = resolvers.resolve(entry, client)
    assert len(specs) == 1
    spec = specs[0]
    assert spec.merge == "geojson"
    assert spec.filename == "wa.geojson"
    assert len(spec.urls) == 2
    assert "resultOffset=0" in spec.urls[0]
    assert "resultOffset=200" in spec.urls[1]
    assert "where=1%3D1" in spec.urls[0] or "where=1=1" in spec.urls[0]
    assert spec.meta["count"] == 305
