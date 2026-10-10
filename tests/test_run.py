"""Fetch orchestration, archive extraction and the manual-source report."""

from __future__ import annotations

import zipfile

import httpx
import pytest
import respx

from fetch import core, run
from fetch.manifest import Entry


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
    with core.HttpClient(contact="a@b.c", backoff_base=0.0, max_attempts=1) as c:
        yield c


@respx.mock
def test_fetch_entry_downloads_and_writes_provenance(tmp_path, client):
    respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"a,b\n", headers={"ETag": '"e"'})
    )
    entry = make_entry(url="https://example.org/data.csv", filename="data.csv")
    prov = run.fetch_entry(entry, client, root=tmp_path)
    assert (tmp_path / "x" / "data.csv").read_bytes() == b"a,b\n"
    record = core.read_provenance(tmp_path / "x" / "_provenance.json")
    assert record["licence"] == "CC-BY-4.0"
    assert record["tier"] == "T1"
    assert record["files"]["data.csv"]["sha256"] == prov["files"]["data.csv"]["sha256"]


@respx.mock
def test_fetch_entry_second_run_refetches_nothing(tmp_path, client):
    route = respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"a,b\n", headers={"ETag": '"e"'})
    )
    entry = make_entry(url="https://example.org/data.csv", filename="data.csv")
    run.fetch_entry(entry, client, root=tmp_path)
    assert route.call_count == 1
    run.fetch_entry(entry, client, root=tmp_path)
    assert route.call_count == 2  # one conditional request; body is not refetched
    record = core.read_provenance(tmp_path / "x" / "_provenance.json")
    assert record["files"]["data.csv"]["skipped"] is True


def test_fetch_entry_skips_manual_and_skip(tmp_path, client):
    entry = make_entry(url="https://example.org/a", status="manual")
    assert run.fetch_entry(entry, client, root=tmp_path)["status"] == "manual"
    assert not (tmp_path / "x").exists()


@respx.mock
def test_fetch_entry_dry_run_writes_nothing(tmp_path, client):
    route = respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"a,b\n")
    )
    entry = make_entry(url="https://example.org/data.csv", filename="data.csv")
    run.fetch_entry(entry, client, root=tmp_path, dry_run=True)
    assert route.call_count == 0
    assert not (tmp_path / "x").exists()


@respx.mock
def test_fetch_entries_filters(tmp_path, client):
    respx.get("https://example.org/a.csv").mock(
        return_value=httpx.Response(200, content=b"a")
    )
    respx.get("https://example.org/b.csv").mock(
        return_value=httpx.Response(200, content=b"b")
    )
    entries = [
        make_entry(id="a", url="https://example.org/a.csv", group="wrecks"),
        make_entry(id="b", url="https://example.org/b.csv", group="trade"),
    ]
    run.fetch_entries(entries, client, root=tmp_path, groups={"trade"})
    assert (tmp_path / "b" / "b.csv").exists()
    assert not (tmp_path / "a").exists()


def test_plan_lines_lists_sources_and_flags_contact():
    entries = [make_entry(id="direct"), make_entry(id="wiki", resolver="wikipedia")]
    text = "\n".join(run.plan_lines(entries, contact="me@example.org"))
    assert "2 source(s) to download" in text
    assert "[needs DR_CONTACT]" in text
    assert "no contact set" not in text


def test_plan_lines_warns_when_contact_missing():
    entries = [make_entry(id="direct"), make_entry(id="wiki", resolver="wikipedia")]
    text = "\n".join(run.plan_lines(entries, contact=None))
    assert "no contact set" in text
    assert "will be refused: wiki" in text


def test_plan_lines_empty_selection():
    assert run.plan_lines([], contact=None) == ["nothing to download"]


def test_extract_entry_unpacks_zip(tmp_path):
    entry = make_entry(id="a")
    dest = tmp_path / "a"
    dest.mkdir(parents=True)
    with zipfile.ZipFile(dest / "data.zip", "w") as zf:
        zf.writestr("inner/file.txt", "hello")
    out = run.extract_entry(entry, root=tmp_path, interim_root=tmp_path / "interim")
    assert (tmp_path / "interim" / "a" / "inner" / "file.txt").read_text() == "hello"
    assert out


def test_manual_report_checks_presence(tmp_path):
    present = make_entry(id="present", status="manual")
    absent = make_entry(id="absent", status="manual")
    (tmp_path / "present").mkdir(parents=True)
    (tmp_path / "present" / "file.zip").write_bytes(b"x")
    report = run.manual_report([present, absent], root=tmp_path)
    by_id = {r["id"]: r for r in report}
    assert by_id["present"]["present"] is True
    assert by_id["absent"]["present"] is False
