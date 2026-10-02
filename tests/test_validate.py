"""Tests for the inventory builder and manifest-generated README."""

from __future__ import annotations

import csv
import json
import zipfile

from fetch import core, validate
from fetch.manifest import Entry


def make_entry(**kwargs) -> Entry:
    base = dict(
        id="ie-wiid",
        group="wrecks",
        title="Wreck Inventory of Ireland",
        resolver="direct",
        licence="CC-BY-4.0",
        tier="T1",
        status="verified",
    )
    base.update(kwargs)
    return Entry(**base)


def test_inspect_csv_counts_rows_and_columns(tmp_path):
    path = tmp_path / "data.csv"
    path.write_text("a,b\n1,2\n3,4\n", encoding="utf-8")
    info = validate.inspect_file(path)
    assert info["kind"] == "csv"
    assert info["rows"] == 2
    assert info["columns"] == "a;b"


def test_inspect_geojson_counts_features(tmp_path):
    path = tmp_path / "data.geojson"
    path.write_text(
        json.dumps(
            {
                "type": "FeatureCollection",
                "features": [{"type": "Feature"}, {"type": "Feature"}],
            }
        ),
        encoding="utf-8",
    )
    info = validate.inspect_file(path)
    assert info["kind"] == "geojson"
    assert info["features"] == 2


def test_inspect_zip_lists_members(tmp_path):
    path = tmp_path / "data.zip"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("a.txt", "a")
        zf.writestr("b.txt", "b")
    info = validate.inspect_file(path)
    assert info["kind"] == "zip"
    assert info["rows"] == 2


def test_inspect_unknown_file(tmp_path):
    path = tmp_path / "data.bin"
    path.write_bytes(b"\x00\x01")
    info = validate.inspect_file(path)
    assert info["kind"] == "bin"


def test_build_inventory_reads_provenance(tmp_path):
    entry = make_entry()
    dest = tmp_path / entry.dest
    dest.mkdir(parents=True)
    (dest / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    core.write_provenance(
        dest / "_provenance.json",
        {
            "id": entry.id,
            "licence": entry.licence,
            "tier": entry.tier,
            "redistribute": True,
            "fetched_at": "2026-10-02T00:00:00Z",
            "files": {"data.csv": {"fetched_at": "2026-10-02T00:00:00Z", "bytes": 8}},
        },
    )
    rows = validate.build_inventory([entry], root=tmp_path)
    assert len(rows) == 1
    row = rows[0]
    assert row["source_id"] == "ie-wiid"
    assert row["file"] == "data.csv"
    assert row["rows"] == 1
    assert row["licence"] == "CC-BY-4.0"
    assert row["sha256"] == core.sha256_file(dest / "data.csv")


def test_build_inventory_ignores_dotfiles(tmp_path):
    entry = make_entry()
    dest = tmp_path / entry.dest
    dest.mkdir(parents=True)
    (dest / ".gitkeep").write_text("", encoding="utf-8")
    (dest / "data.csv").write_text("a\n1\n", encoding="utf-8")
    rows = validate.build_inventory([entry], root=tmp_path)
    assert [r["file"] for r in rows] == ["data.csv"]


def test_write_inventory_writes_csv(tmp_path):
    entry = make_entry()
    dest = tmp_path / entry.dest
    dest.mkdir(parents=True)
    (dest / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    out = validate.write_inventory([entry], root=tmp_path)
    with open(out, newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert rows[0]["source_id"] == "ie-wiid"
    assert "sha256" in rows[0]


def test_write_readme_from_manifest(tmp_path):
    entry = make_entry()
    dest = tmp_path / entry.dest
    dest.mkdir(parents=True)
    (dest / "data.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    core.write_provenance(
        dest / "_provenance.json",
        {"licence": entry.licence, "files": {"data.csv": {"fetched_at": "2026-10-02T00:00:00Z"}}},
    )
    out = validate.write_readme([entry], root=tmp_path)
    text = out.read_text(encoding="utf-8")
    assert "Wreck Inventory of Ireland" in text
    assert "CC-BY-4.0" in text
    assert "ie-wiid" in text
