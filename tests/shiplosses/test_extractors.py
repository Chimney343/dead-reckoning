"""Synthetic extractor tests reproducing the real quirks (plan section 10)."""

from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from shiplosses.sources import ukho, wa, zenodo

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "shiplosses"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def _raw(relative: str) -> Path:
    path = RAW / relative
    if not path.exists():
        pytest.skip(f"real data absent: {relative}")
    return path


@pytest.mark.real_data
def test_golden_source_counts():
    """Pin today's snapshot; bump on purpose when a source is refetched."""
    with zipfile.ZipFile(_raw("ukho-wrecks/extra/ukho-wrecks-extra.zip")) as bundle:
        raw_text = bundle.read("Wrecks.txt").decode("utf-8")
    assert len(raw_text.splitlines()) - 1 == 102625

    wa_payload = json.loads(_raw("wa-shipwrecks/wa-shipwrecks.geojson").read_text("utf-8"))
    assert len(wa_payload["features"]) == 305

    with _raw("zenodo-shipwrecks/shipWrecks.csv").open(encoding="utf-8-sig", newline="") as handle:
        zenodo_rows = list(csv.reader(handle))
    assert len(zenodo_rows) - 1 == 4463


@pytest.mark.real_data
def test_golden_extractor_outputs():
    root = RAW
    ukho_extract = ukho.extract(root)
    assert len(ukho_extract.losses) > 80000
    assert ukho_extract.losses["loss_id"].is_unique
    assert len(wa.extract(root).losses) == 301
    assert len(zenodo.extract(root).losses) == 4463



def test_ukho_extractor_reads_quoted_tsv(tmp_path):
    root = tmp_path / "raw"
    target = root / "ukho-wrecks" / "extra"
    target.mkdir(parents=True)
    with zipfile.ZipFile(target / "ukho-wrecks-extra.zip", "w") as bundle:
        bundle.write(FIXTURES / "ukho_wrecks.tsv", "Wrecks.txt")

    extract = ukho.extract(root)
    assert len(extract.losses) == 3
    assert extract.losses["loss_id"].is_unique
    wrecks = extract.losses.set_index("ship_name")
    citra = wrecks.loc["Citra Mulya IX"]
    assert citra["lat"] == pytest.approx(-5.558917, abs=1e-6)
    assert citra["lon"] == pytest.approx(110.962667, abs=1e-6)
    assert citra["flag_at_loss_polity"] == "Great Britain"
    assert citra["owner_at_loss"] == "JOHN SMITH"
    assert citra["origin_basis"] == "built"
    assert "SEA TRANSPORTER" in citra["former_names"]
    assert not any(extract.losses["ship_name"] == "")


def test_wa_extractor_drops_non_losses(tmp_path):
    root = tmp_path / "raw"
    target = root / "wa-shipwrecks"
    target.mkdir(parents=True)
    (target / "wa-shipwrecks.geojson").write_text(
        (FIXTURES / "wa_shipwrecks.geojson").read_text(encoding="utf-8"), encoding="utf-8"
    )

    extract = wa.extract(root)
    assert len(extract.losses) == 2
    assert not set(extract.losses["ship_name"]) & {"Refloat Me"}
    wrecked = extract.losses.set_index("ship_name").loc["Batavia"]
    assert wrecked["lat"] == pytest.approx(-28.8)
    assert wrecked["cause_class"] == "stranded"
    assert wrecked["origin_polity"] == "Netherlands"


def test_zenodo_extractor_strips_bom_and_placeholder(tmp_path):
    root = tmp_path / "raw"
    target = root / "zenodo-shipwrecks"
    target.mkdir(parents=True)
    header = ["", "SHIP", "FLAG", "SUNK DATE", "VESSEL TYPE", "ZONA1", "ZONA2", "ZONA3",
              "ZONA4", "COORDINATES", "NOTES", "IMAGE"]
    rows = [
        ["0", "Globe Star", "United Kingdom", "01/01/1805", "", "", "", "", "",
         "-4.0818;39.72\ufeff", "A cargo ship that ran aground off Mombasa.", ""],
        ["1", "Mary", "France", "14/03/1797", "", "", "", "", "",
         "", "A ship of the line wrecked off Le Croisic.", ""],
    ]
    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(header)
    writer.writerows(rows)
    (target / "shipWrecks.csv").write_text(buffer.getvalue(), encoding="utf-8-sig")

    extract = zenodo.extract(root)
    assert len(extract.losses) == 2
    star = extract.losses.set_index("ship_name").loc["Globe Star"]
    assert star["lat"] == pytest.approx(-4.0818)
    assert star["lon"] == pytest.approx(39.72)
    assert star["loss_date"] == "1805"
    assert star["date_precision"] == "year"
    assert star["flag_at_loss_polity"] == "United Kingdom"
    mary = extract.losses.set_index("ship_name").loc["Mary"]
    assert mary["cause_class"] == "stranded"
    assert mary["loss_date"] == "1797-03-14"
