"""The fixture fetcher refuses to send an anonymous User-Agent (rule 2)."""

from __future__ import annotations

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
