"""Manifest schema, loading and selection, plus checks on the real manifest."""

from __future__ import annotations

import textwrap

import pytest
import yaml

from fetch import manifest as m

SAMPLE = textwrap.dedent(
    """
    - id: ie-wiid
      group: wrecks
      title: Wreck Inventory of Ireland
      resolver: direct
      url: https://example.org/wiid.csv
      licence: CC-BY-4.0
      tier: T1
      status: verified
      approx_bytes: 5000000
      redistribute: true
      notes: DD_Lat/DD_Long == 0 means unlocated
    - id: prize-papers
      group: captures
      title: Prize Papers portal
      resolver: prizepapers
      url: https://portal.prizepapers.de/api/v1/
      licence: Metadata terms unstated
      tier: T1
      status: verified
      large: false
      redistribute: false
    - id: stro-sound-toll
      group: routes
      title: STRO 2.0
      resolver: figshare
      url: https://api.figshare.com/v2/articles/27176202
      licence: CC-BY-4.0
      tier: T1
      status: verified
      large: true
      redistribute: true
    """
).strip()


@pytest.fixture
def entries(tmp_path):
    path = tmp_path / "manifest.yaml"
    path.write_text(SAMPLE, encoding="utf-8")
    return m.load_manifest(path)


def test_load_manifest_parses_fields(entries):
    entry = entries[0]
    assert entry.id == "ie-wiid"
    assert entry.group == "wrecks"
    assert entry.resolver == "direct"
    assert entry.approx_bytes == 5_000_000
    assert entry.redistribute is True
    assert entry.large is False
    assert "unlocated" in entry.notes


def test_load_manifest_defaults_optional_fields(entries):
    entry = entries[1]
    assert entry.filename is None
    assert entry.approx_bytes == 0
    assert entry.large is False
    assert entry.notes == ""
    assert entry.rate_limit is None


def test_load_manifest_rejects_missing_required(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text("- id: x\n  group: wrecks\n", encoding="utf-8")
    with pytest.raises(m.ManifestError, match="missing required"):
        m.load_manifest(path)


def test_load_manifest_rejects_unknown_group(tmp_path):
    path = tmp_path / "bad.yaml"
    path.write_text(
        "- id: x\n  group: nope\n  title: t\n  resolver: direct\n"
        "  licence: l\n  tier: T1\n  status: verified\n  url: https://e.org/a\n",
        encoding="utf-8",
    )
    with pytest.raises(m.ManifestError, match="unknown group"):
        m.load_manifest(path)


def test_load_manifest_rejects_duplicate_ids(tmp_path):
    path = tmp_path / "dup.yaml"
    path.write_text(SAMPLE + "\n" + SAMPLE, encoding="utf-8")
    with pytest.raises(m.ManifestError, match="duplicate id"):
        m.load_manifest(path)


def test_select_filters_by_group_and_large(entries):
    assert [e.id for e in m.select(entries, groups={"captures"})] == ["prize-papers"]
    assert [e.id for e in m.select(entries, groups={"routes"})] == []
    assert [e.id for e in m.select(entries, groups={"routes"}, include_large=True)] == [
        "stro-sound-toll"
    ]


def test_select_filters_by_id_overrides_group(entries):
    got = m.select(entries, ids={"ie-wiid"}, include_large=True)
    assert [e.id for e in got] == ["ie-wiid"]
    got = m.select(
        entries, ids={"ie-wiid", "stro-sound-toll"}, groups={"routes"}, include_large=True
    )
    assert sorted(e.id for e in got) == ["ie-wiid", "stro-sound-toll"]


def test_get_entry(entries):
    assert m.get_entry(entries, "ie-wiid").group == "wrecks"
    with pytest.raises(KeyError):
        m.get_entry(entries, "missing")


# --- checks on the committed manifest -------------------------------------


def test_real_manifest_loads():
    entries = m.load_manifest()
    assert len(entries) >= 30


def test_real_manifest_ids_unique_and_statuses_final():
    entries = m.load_manifest()
    m.validate_statuses(entries)


def test_real_manifest_resolvers_registered():
    from fetch import harvesters, resolvers

    entries = m.load_manifest()
    known = set(resolvers.RESOLVERS) | set(harvesters.HARVESTERS)
    unknown = sorted({e.resolver for e in entries} - known)
    assert unknown == []


def test_real_manifest_yaml_is_list():
    raw = yaml.safe_load(m.manifest_path().read_text(encoding="utf-8"))
    assert isinstance(raw, list)
