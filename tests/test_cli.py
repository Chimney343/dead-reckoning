"""CLI smoke tests (no network)."""

from __future__ import annotations

from fetch import __main__ as cli
from fetch.manifest import Entry


def sample_entries():
    return [
        Entry(
            id="a",
            group="wrecks",
            title="Source A",
            resolver="direct",
            url="https://example.org/a.csv",
            licence="CC-BY-4.0",
            tier="T1",
            status="verified",
        ),
        Entry(
            id="b",
            group="routes",
            title="Source B",
            resolver="direct",
            url="https://example.org/b",
            licence="None stated",
            tier="T1",
            status="manual",
            notes="fetch by hand",
        ),
    ]


def test_list_prints_sources(monkeypatch, capsys):
    entries = sample_entries()
    monkeypatch.setattr(cli.manifest, "load_manifest", lambda: entries)
    assert cli.main(["list"]) == 0
    out = capsys.readouterr().out
    assert "a" in out and "b" in out and "CC-BY-4.0" in out


def test_get_dry_run_makes_no_network(monkeypatch, capsys):
    entries = sample_entries()
    monkeypatch.setattr(cli.manifest, "load_manifest", lambda: entries)
    monkeypatch.setattr(cli.core, "resolve_contact", lambda: None)
    assert cli.main(["get", "--dry-run", "--id", "a"]) == 0
    out = capsys.readouterr().out
    assert "a" in out


def test_manual_lists_instructions(monkeypatch, capsys):
    entries = sample_entries()
    monkeypatch.setattr(cli.manifest, "load_manifest", lambda: entries)
    assert cli.main(["manual"]) == 0
    out = capsys.readouterr().out
    assert "b" in out and "fetch by hand" in out


def test_unknown_id_errors(monkeypatch, capsys):
    entries = sample_entries()
    monkeypatch.setattr(cli.manifest, "load_manifest", lambda: entries)
    assert cli.main(["extract", "nope"]) == 2
    assert "nope" in capsys.readouterr().err
