"""Synthetic and golden tests for the phase-4 text-location extractors."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pandas as pd
import pytest
from shiplosses.sources import das, emodnet, ibm, infomar, novascotia, wiid

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "shiplosses"
RAW = Path(__file__).resolve().parents[2] / "data" / "raw"


def _target(tmp_path: Path, dest: str) -> Path:
    target = tmp_path / "raw" / dest
    target.mkdir(parents=True, exist_ok=True)
    return target


def _copy_fixture(name: str, destination: Path, target_name: str | None = None) -> None:
    (destination / (target_name or name)).write_bytes((FIXTURES / name).read_bytes())


def test_wiid_extractor_reads_bom(tmp_path):
    target = _target(tmp_path, "ireland-wiid")
    _copy_fixture("wiid_bom.csv", target, "wiid.csv")

    extract = wiid.extract(tmp_path / "raw")
    assert len(extract.losses) == 3
    assert extract.losses["loss_id"].is_unique

    frame = extract.losses.set_index("ship_name")
    actur = frame.loc["Actur"]
    assert actur["source_record_id"] == "W00001"
    assert actur["ship_type"] == "Schooner"
    assert actur["cause_class"] == "stranded"
    assert actur["location_precision"] == "place"
    assert actur["uncertainty_km"] == pytest.approx(10.0)

    anne = frame.loc["Anne McLeod"]
    assert anne["cause_class"] == "foundered"
    assert anne["weather_related"]

    boaty = frame.loc["Boaty"]
    assert boaty["lat"] == pytest.approx(53.5)
    assert boaty["lon"] == pytest.approx(-6.2)
    assert boaty["location_precision"] == "reported"
    assert boaty["uncertainty_km"] == pytest.approx(5.0)
    assert pd.isna(boaty["cause_raw"])
    assert boaty["cause_class"] == "unknown"
    assert boaty["loss_date"] == "1900"
    assert boaty["date_precision"] == "year"


def test_emodnet_extractor_handles_na(tmp_path):
    target = _target(tmp_path, "emodnet-shipwrecks")
    _copy_fixture("emodnet_shipwrecks.geojson", target, "emodnet-shipwrecks.geojson")

    extract = emodnet.extract(tmp_path / "raw")
    assert len(extract.losses) == 3
    assert extract.losses["loss_id"].is_unique

    frame = extract.losses.set_index("source_record_id")
    schiedam = frame.loc["1000049"]
    assert schiedam["lat"] == pytest.approx(50.03943289)
    assert schiedam["lon"] == pytest.approx(-5.27436077)
    assert schiedam["location_precision"] == "reported"
    assert schiedam["uncertainty_km"] == pytest.approx(5.0)
    assert schiedam["cause_class"] == "stranded"
    assert schiedam["ship_type"] == "Transport vessel"
    assert schiedam["route_from"] == "Tangier"
    assert pd.isna(schiedam["route_to"])
    assert schiedam["loss_date"] == "1684"

    blank = frame.loc["2"]
    assert pd.isna(blank["ship_name"])
    assert pd.isna(blank["cause_raw"])
    assert blank["cause_class"] == "unknown"

    no_geom = frame.loc["3"]
    assert pd.isna(no_geom["lat"])


def test_novascotia_extractor_strips_suffix_and_nonlosses(tmp_path):
    target = _target(tmp_path, "novascotia-shipwrecks")
    _copy_fixture("novascotia_shipwrecks.csv", target, "novascotia-shipwrecks.csv")

    extract = novascotia.extract(tmp_path / "raw")
    assert len(extract.losses) == 4
    assert set(extract.losses["source_record_id"]) == {"0", "1", "2", "3"}

    frame = extract.losses.set_index("ship_name")
    stronza = frame.loc["Stronza"]
    assert stronza["cause_class"] == "stranded"
    assert stronza["location_precision"] == "place"
    assert stronza["route_from"] == "Dublin"
    assert bool(stronza["is_total_loss"])

    for name in ("Damagey", "Lospar", "Serious"):
        assert not bool(frame.loc[name, "is_total_loss"])


def test_das_extractor_semicolons_and_loss_only(tmp_path):
    target = _target(tmp_path, "dutch-asiatic-shipping")
    _copy_fixture("das_voyages.csv", target, "voyages_with_details.csv")

    extract = das.extract(tmp_path / "raw")
    assert len(extract.losses) == 2
    assert "DUIFJE" not in set(extract.losses["ship_name"])

    frame = extract.losses.set_index("ship_name")
    amsterdam = frame.loc["AMSTERDAM"]
    assert amsterdam["cause_class"] == "fire_explosion"
    assert amsterdam["owner_at_loss"] == "VOC Amsterdam"
    assert amsterdam["flag_at_loss_polity"] == "Dutch Republic"
    assert amsterdam["licence"] == "None stated"
    assert not bool(amsterdam["redistribute"])

    hoop = frame.loc["GOEDE HOOP"]
    assert hoop["location_text"] == "near Cape Agulhas"
    assert hoop["location_precision"] == "place"
    assert hoop["loss_date"] == "1730-01-08"
    assert hoop["date_precision"] == "day"


def test_infomar_extractor_reads_zipped_shapefile(tmp_path):
    import geopandas as gpd

    target = _target(tmp_path, "ireland-infomar")
    work = tmp_path / "shp"
    work.mkdir()
    gdf = gpd.GeoDataFrame(
        {
            "latitude": [51.0, 52.0],
            "longitude": [-9.0, -6.0],
            "vesselname": ["SS Ardmore", ""],
            "date_loss": pd.to_datetime(["1940-11-11", None]),
            "nms_ref": ["W03182", ""],
        },
        geometry=gpd.points_from_xy([-9.0, -6.0], [51.0, 52.0]),
        crs="EPSG:4326",
    )
    gdf.to_file(work / "wrecks.shp")
    with zipfile.ZipFile(target / "wrecks.zip", "w") as archive:
        for path in work.iterdir():
            if path.suffix in {".shp", ".dbf", ".shx", ".prj", ".cpg"}:
                archive.write(path, path.name)

    extract = infomar.extract(tmp_path / "raw")
    assert len(extract.losses) == 2
    assert extract.losses["loss_id"].is_unique

    frame = extract.losses.set_index("source_record_id")
    ardmore = frame.loc["W03182"]
    assert ardmore["ship_name"] == "SS Ardmore"
    assert ardmore["lat"] == pytest.approx(51.0)
    assert ardmore["lon"] == pytest.approx(-9.0)
    assert ardmore["location_precision"] == "surveyed"
    assert ardmore["uncertainty_km"] == pytest.approx(0.1)
    assert ardmore["loss_date"] == "1940-11-11"

    fallback = frame.loc["1"]
    assert pd.isna(fallback["ship_name"])


def test_ibm_extractor_curated_and_voc(tmp_path):
    target = _target(tmp_path, "ibm-maritime-archives")
    prefix = "repo-HEAD/data/"
    wrecks = [
        {
            "wreck_id": "maarer:0001.1",
            "ship_name": "AMSTERDAM",
            "loss_cause": "fire",
            "loss_date": "1597-01-11",
            "loss_location": "Bawean",
            "departure_port": "Texel",
            "destination_port": "Engano",
        },
        {
            "wreck_id": "maarer:0002.1",
            "ship_name": "UNKNOWN DATE",
            "loss_cause": "lost",
            "loss_date": None,
            "loss_location": "",
        },
    ]
    carreira = [
        {
            "wreck_id": "carreira_wreck:0001",
            "ship_name": "Sao Joao",
            "loss_cause": "storm",
            "loss_date": "1552-06-11",
            "loss_location": "Natal coast",
            "position": {"lat": -31.0, "lon": 30.2, "uncertainty_km": 50},
            "is_curated": True,
        },
        {
            "wreck_id": "carreira_wreck:0002",
            "ship_name": "No Position",
            "loss_cause": "wrecked",
            "loss_date": "1600-01-01",
            "loss_location": "Somewhere",
            "is_curated": True,
        },
        {
            "wreck_id": "carreira_wreck:0003",
            "ship_name": "Synthetic",
            "loss_cause": "storm",
            "loss_date": "1529-01-01",
            "position": {"lat": 0.0, "lon": 0.0, "uncertainty_km": 1},
            "is_curated": False,
        },
    ]
    soic = [
        {
            "wreck_id": "soic_wreck:0001",
            "ship_name": "Gotheborg",
            "loss_cause": "grounding",
            "loss_date": "1745-09-12",
            "loss_location": "Gothenburg harbour",
            "position": {"lat": 57.68, "lon": 11.82, "uncertainty_km": 0.5},
            "is_curated": True,
        }
    ]
    with zipfile.ZipFile(target / "chuk-mcp-maritime-archives-HEAD.zip", "w") as archive:
        archive.writestr(prefix + "wrecks.json", json.dumps(wrecks))
        archive.writestr(prefix + "carreira_wrecks.json", json.dumps(carreira))
        archive.writestr(prefix + "soic_wrecks.json", json.dumps(soic))

    extract = ibm.extract(tmp_path / "raw")
    assert len(extract.losses) == 5
    assert extract.losses["loss_id"].is_unique

    frame = extract.losses.set_index("source_record_id")
    amsterdam = frame.loc["maarer:0001.1"]
    assert amsterdam["owner_at_loss"] == "VOC"
    assert amsterdam["flag_at_loss_polity"] == "Dutch Republic"
    assert amsterdam["cause_class"] == "fire_explosion"
    assert amsterdam["loss_date"] == "1597-01-11"
    assert amsterdam["location_precision"] == "place"

    sao = frame.loc["carreira_wreck:0001"]
    assert sao["lat"] == pytest.approx(-31.0)
    assert sao["lon"] == pytest.approx(30.2)
    assert sao["location_precision"] == "reported"
    assert sao["uncertainty_km"] == pytest.approx(50.0)
    assert sao["flag_at_loss_polity"] == "Portugal"
    assert sao["cause_class"] == "weather"

    no_position = frame.loc["carreira_wreck:0002"]
    assert no_position["location_precision"] == "place"
    assert no_position["uncertainty_km"] == pytest.approx(10.0)

    gotheborg = frame.loc["soic_wreck:0001"]
    assert gotheborg["location_precision"] == "surveyed"
    assert gotheborg["uncertainty_km"] == pytest.approx(0.5)
    assert gotheborg["flag_at_loss_polity"] == "Sweden"


@pytest.mark.real_data
def test_golden_counts_phase4():
    """Pin today's snapshot; bump on purpose when a source is refetched."""
    if not RAW.exists():
        pytest.skip("real data absent")

    assert len(wiid.extract(RAW).losses) == 17981
    assert len(infomar.extract(RAW).losses) == 608
    assert len(emodnet.extract(RAW).losses) == 7073
    assert len(novascotia.extract(RAW).losses) == 4939
    assert len(das.extract(RAW).losses) == 637
    assert len(ibm.extract(RAW).losses) == 830
