"""Live checks: one request per verified source.

Run with ``pytest -m network``. Not part of the offline suite.
"""

from __future__ import annotations

from urllib.parse import quote

import httpx
import pytest

from fetch import core, manifest

pytestmark = pytest.mark.network

UA = core.build_user_agent("network-test")


def _targets() -> list[tuple[str, str]]:
    targets: list[tuple[str, str]] = []
    for entry in manifest.load_manifest():
        if entry.status != "verified":
            continue
        if entry.resolver == "prizepapers":
            targets.append((entry.id, entry.url.rstrip("/") + "/openapi.json"))
        elif entry.resolver == "wikidata":
            query = quote("SELECT ?s WHERE { ?s ?p ?o } LIMIT 1")
            targets.append((entry.id, f"{entry.url}?query={query}&format=json"))
        elif entry.resolver == "wikipedia":
            targets.append((entry.id, entry.url + "?action=query&meta=siteinfo&format=json"))
        elif entry.urls:
            for url in entry.urls:
                targets.append((entry.id, url))
        else:
            targets.append((entry.id, entry.url))
    return targets


@pytest.mark.parametrize("entry_id,url", _targets(), ids=lambda v: str(v)[:60])
def test_verified_url_reachable(entry_id, url):
    with httpx.Client(
        follow_redirects=True, timeout=30.0, headers={"User-Agent": UA}
    ) as client:
        response = client.head(url)
        if response.status_code >= 400:
            response = client.get(url, headers={"Range": "bytes=0-0"})
        assert response.status_code < 400, f"{entry_id} {url} -> {response.status_code}"
