"""Tests for the download core: contact handling, rate limiting, retries,
streaming with resume, skip-if-unchanged, checksums and provenance."""

from __future__ import annotations

import hashlib
import json

import httpx
import pytest
import respx

from fetch import core

# --- contact / user agent -------------------------------------------------


def test_resolve_contact_reads_environment(monkeypatch):
    monkeypatch.setenv("DR_CONTACT", "someone@example.org")
    assert core.resolve_contact() == "someone@example.org"


def test_resolve_contact_reads_dotenv(tmp_path, monkeypatch):
    monkeypatch.delenv("DR_CONTACT", raising=False)
    env = tmp_path / ".env"
    env.write_text('DR_CONTACT="dotenv@example.org"\n', encoding="utf-8")
    assert core.resolve_contact(dotenv_path=env) == "dotenv@example.org"


def test_resolve_contact_none_when_unset(tmp_path, monkeypatch):
    monkeypatch.delenv("DR_CONTACT", raising=False)
    assert core.resolve_contact(dotenv_path=tmp_path / "missing.env") is None


def test_build_user_agent_contains_contact():
    ua = core.build_user_agent("a@b.c")
    assert ua.startswith("dead-reckoning-fetch/")
    assert "a@b.c" in ua


def test_build_user_agent_without_contact_still_identifies_project():
    ua = core.build_user_agent(None)
    assert "dead-reckoning" in ua


# --- rate limiter ---------------------------------------------------------


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def test_rate_limiter_waits_between_same_host_requests():
    clock = FakeClock()
    limiter = core.RateLimiter(default_gap=1.0, clock=clock.monotonic, sleep=clock.sleep)
    limiter.wait("example.org")
    clock.now += 0.25
    limiter.wait("example.org")
    assert clock.slept == [0.75]


def test_rate_limiter_is_independent_per_host():
    clock = FakeClock()
    limiter = core.RateLimiter(default_gap=1.0, clock=clock.monotonic, sleep=clock.sleep)
    limiter.wait("a.example.org")
    limiter.wait("b.example.org")
    assert clock.slept == []


def test_rate_limiter_honours_per_host_override():
    clock = FakeClock()
    limiter = core.RateLimiter(
        default_gap=1.0,
        per_host={"slow.example.org": 5.0},
        clock=clock.monotonic,
        sleep=clock.sleep,
    )
    limiter.wait("slow.example.org")
    limiter.wait("slow.example.org")
    assert clock.slept == [5.0]


# --- sha256 / provenance --------------------------------------------------


def test_sha256_file(tmp_path):
    p = tmp_path / "x.bin"
    p.write_bytes(b"hello")
    assert core.sha256_file(p) == hashlib.sha256(b"hello").hexdigest()


def test_write_and_read_provenance_round_trip(tmp_path):
    path = tmp_path / "_provenance.json"
    data = {"id": "x", "files": {"a.csv": {"bytes": 3}}}
    core.write_provenance(path, data)
    assert core.read_provenance(path) == data
    # written atomically: no leftover temp file
    assert [p.name for p in tmp_path.iterdir()] == ["_provenance.json"]


def test_read_provenance_missing_returns_empty(tmp_path):
    assert core.read_provenance(tmp_path / "nope.json") == {}


# --- retries --------------------------------------------------------------


@respx.mock
def test_get_retries_on_500_then_succeeds():
    route = respx.get("https://example.org/data.csv").mock(
        side_effect=[
            httpx.Response(500),
            httpx.Response(200, text="ok"),
        ]
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        response = client.get("https://example.org/data.csv")
    assert response.status_code == 200
    assert route.call_count == 2


@respx.mock
def test_get_honours_retry_after_header(monkeypatch):
    sleeps = []
    monkeypatch.setattr(core.time, "sleep", lambda s: sleeps.append(s))
    respx.get("https://example.org/data.csv").mock(
        side_effect=[
            httpx.Response(429, headers={"Retry-After": "7"}),
            httpx.Response(200, text="ok"),
        ]
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        response = client.get("https://example.org/data.csv")
    assert response.status_code == 200
    assert 7.0 in sleeps


@respx.mock
def test_get_gives_up_after_max_attempts():
    respx.get("https://example.org/data.csv").mock(return_value=httpx.Response(503))
    with core.HttpClient(contact="a@b.c", backoff_base=0.0, max_attempts=3) as client:
        with pytest.raises(core.DownloadError):
            client.get("https://example.org/data.csv")


# --- streaming download ---------------------------------------------------


@respx.mock
def test_download_file_writes_bytes_and_provenance_fields(tmp_path):
    body = b"col1,col2\n1,2\n"
    respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(
            200,
            content=body,
            headers={"ETag": '"abc"', "Last-Modified": "Wed, 01 Jan 2025 00:00:00 GMT"},
        )
    )
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path)
    assert (tmp_path / "data.csv").read_bytes() == body
    assert not (tmp_path / "data.csv.part").exists()
    assert result.bytes == len(body)
    assert result.sha256 == hashlib.sha256(body).hexdigest()
    assert result.etag == '"abc"'
    assert result.status == 200
    assert result.skipped is False


@respx.mock
def test_download_file_resumes_from_part(tmp_path):
    part = tmp_path / "data.csv.part"
    part.write_bytes(b"col1,col2\n")
    seen = {}

    def responder(request):
        seen["range"] = request.headers.get("range")
        return httpx.Response(206, content=b"1,2\n")

    respx.get("https://example.org/data.csv").mock(side_effect=responder)
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path)
    assert seen["range"] == "bytes=10-"
    assert (tmp_path / "data.csv").read_bytes() == b"col1,col2\n1,2\n"
    assert result.bytes == 14


@respx.mock
def test_download_file_restarts_when_server_ignores_range(tmp_path):
    part = tmp_path / "data.csv.part"
    part.write_bytes(b"stale")
    respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"fresh-body")
    )
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        core.download_file(client, spec, tmp_path)
    assert (tmp_path / "data.csv").read_bytes() == b"fresh-body"


@respx.mock
def test_download_file_skips_on_304(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"old")
    prior = {"bytes": 3, "etag": '"abc"'}
    respx.get("https://example.org/data.csv").mock(return_value=httpx.Response(304))
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path, prior=prior)
    assert result.skipped is True
    assert dest.read_bytes() == b"old"


@respx.mock
def test_download_file_skips_when_size_matches_without_validators(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"same-size")
    prior = {"bytes": 9}
    respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"same-size")
    )
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path, prior=prior)
    assert result.skipped is True


@respx.mock
def test_download_file_skips_when_no_content_length_and_size_matches(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"same-size")
    prior = {"bytes": 9}
    response = httpx.Response(200, content=b"same-size")
    del response.headers["content-length"]
    respx.get("https://example.org/data.csv").mock(return_value=response)
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path, prior=prior)
    assert result.skipped is True


@respx.mock
def test_download_file_skips_when_response_etag_matches(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"same-size")
    prior = {"bytes": 9, "etag": '"abc"'}
    response = httpx.Response(200, content=b"same-size", headers={"ETag": '"abc"'})
    del response.headers["content-length"]
    respx.get("https://example.org/data.csv").mock(return_value=response)
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path, prior=prior)
    assert result.skipped is True


@respx.mock
def test_download_file_force_redownloads(tmp_path):
    dest = tmp_path / "data.csv"
    dest.write_bytes(b"old")
    respx.get("https://example.org/data.csv").mock(
        return_value=httpx.Response(200, content=b"new"))
    spec = core.FileSpec(urls=["https://example.org/data.csv"], filename="data.csv")
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path, prior={"bytes": 3}, force=True)
    assert result.skipped is False
    assert dest.read_bytes() == b"new"


@respx.mock
def test_download_file_merges_geojson_pages(tmp_path):
    page = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"i": 1}}]}
    page2 = {"type": "FeatureCollection", "features": [{"type": "Feature", "properties": {"i": 2}}]}
    respx.get("https://example.org/q?page=1").mock(return_value=httpx.Response(200, json=page))
    respx.get("https://example.org/q?page=2").mock(return_value=httpx.Response(200, json=page2))
    spec = core.FileSpec(
        urls=["https://example.org/q?page=1", "https://example.org/q?page=2"],
        filename="wrecks.geojson",
        merge="geojson",
    )
    with core.HttpClient(contact="a@b.c", backoff_base=0.0) as client:
        result = core.download_file(client, spec, tmp_path)
    data = json.loads((tmp_path / "wrecks.geojson").read_text())
    assert len(data["features"]) == 2
    assert result.bytes > 0
