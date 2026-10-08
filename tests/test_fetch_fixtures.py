"""The fixture fetcher refuses to send an anonymous User-Agent (rule 2)."""

from __future__ import annotations

from threedecks.lock import CrawlLock

import scripts.fetch_fixtures as fetch_fixtures


def test_refuses_without_a_contact_and_touches_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.delenv("THREEDECKS_CONTACT", raising=False)
    fixture_dir = tmp_path / "real"
    monkeypatch.setattr(fetch_fixtures, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(fetch_fixtures, "INDEX_PATH", fixture_dir / "_index.json")

    assert fetch_fixtures.main([]) == 2
    assert "THREEDECKS_CONTACT" in capsys.readouterr().err
    # An empty fixtures folder would un-skip the golden tests, so none is created.
    assert not fixture_dir.exists()


def test_refuses_while_another_crawl_holds_the_lock(monkeypatch, tmp_path, capsys):
    """Rule 10: the fixture fetcher shares the crawl lock, so it never fetches
    alongside a live crawl (and never constructs an HTTP client)."""
    monkeypatch.setenv("THREEDECKS_CONTACT", "test@example.org")
    monkeypatch.setattr(fetch_fixtures, "DATA_DIR", tmp_path)
    fixture_dir = tmp_path / "real"
    monkeypatch.setattr(fetch_fixtures, "FIXTURE_DIR", fixture_dir)
    monkeypatch.setattr(fetch_fixtures, "INDEX_PATH", fixture_dir / "_index.json")

    def no_client(*args, **kwargs):  # a request here would be a bug
        raise AssertionError("httpx.Client must not be constructed while locked")

    monkeypatch.setattr(fetch_fixtures.httpx, "Client", no_client)

    with CrawlLock(tmp_path / "crawl.lock"):
        assert fetch_fixtures.main([]) == 2
    assert "holds" in capsys.readouterr().err
