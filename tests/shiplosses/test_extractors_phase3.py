"""Phase 3 extractor tests: SlaveVoyages, Prize Papers and Todo a Babor."""

from __future__ import annotations

import csv
import importlib.util
import io
import json
from pathlib import Path

import pytest
from shiplosses.sources import prizepapers, slavevoyages, todoababor

RAW = Path(__file__).resolve().parents[2] / "data" / "raw"
SCRIPT = (
    Path(__file__).resolve().parents[2]
    / "analyses"
    / "01-ship-losses"
    / "scripts"
    / "sv_codebook.py"
)

SV_COLUMNS = [
    "VOYAGEID",
    "FATE",
    "FATE3",
    "NATIONAL",
    "YEARAM",
    "SHIPNAME",
    "RIG",
    "OWNERA",
    "MJBYPTIMP",
    "PLAC1TRA",
    "SLA1PORT",
    "MJSLPTIMP",
]


def _raw(relative: str) -> Path:
    path = RAW / relative
    if not path.exists():
        pytest.skip(f"real data absent: {relative}")
    return path


def _load_codebook():
    spec = importlib.util.spec_from_file_location("sv_codebook", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_slavevoyages(root: Path, rows: list[dict[str, str]]) -> None:
    target = root / "slavevoyages"
    target.mkdir(parents=True)
    buffer = io.StringIO()
    writer = csv.DictWriter(buffer, fieldnames=SV_COLUMNS)
    writer.writeheader()
    writer.writerows(rows)
    (target / "tastdb-exp-2019.csv").write_text(buffer.getvalue(), encoding="utf-8")


def test_extractors_return_empty_when_absent(tmp_path):
    root = tmp_path / "raw"
    for module in (slavevoyages, prizepapers, todoababor):
        extract = module.extract(root)
        assert extract.losses.empty
        assert extract.events.empty


def test_slavevoyages_classifies_losses_and_captures(tmp_path):
    rows = [
        {
            "VOYAGEID": "V1",
            "FATE": "2",
            "NATIONAL": "7",
            "YEARAM": "1790",
            "SHIPNAME": "Sea Flower",
            "RIG": "4",
            "OWNERA": "Royal African Company",
            "MJBYPTIMP": "10432",
        },
        {
            "VOYAGEID": "V2",
            "FATE": "3",
            "NATIONAL": "4",
            "YEARAM": "1750",
            "SHIPNAME": "Nossa",
            "MJBYPTIMP": "60799",
        },
        {
            "VOYAGEID": "V3",
            "FATE": "4",
            "NATIONAL": "10",
            "YEARAM": "1760",
            "SHIPNAME": "Dauphin",
            "SLA1PORT": "50422",
        },
        {"VOYAGEID": "V4", "FATE": "10", "FATE3": "3", "NATIONAL": "7", "SHIPNAME": "Harriet"},
        {"VOYAGEID": "V5", "FATE": "102", "NATIONAL": "9", "SHIPNAME": "Antelope"},
        {"VOYAGEID": "V6", "FATE": "1", "NATIONAL": "7", "SHIPNAME": "Completed"},
        {"VOYAGEID": "V7", "FATE": "44", "NATIONAL": "7", "SHIPNAME": "Abandoned"},
    ]
    _write_slavevoyages(tmp_path, rows)
    extract = slavevoyages.extract(tmp_path)

    assert len(extract.losses) == 3
    assert len(extract.events) == 2
    losses = extract.losses.set_index("ship_name")

    flower = losses.loc["Sea Flower"]
    assert flower["location_text"] == "Liverpool"
    assert flower["location_precision"] == "place"
    assert flower["flag_at_loss_polity"] == "Great Britain"
    assert flower["owner_at_loss"] == "Royal African Company"
    assert flower["cause_class"] == "stranded"
    assert flower["loss_date"] == "1790"
    assert bool(flower["redistribute"]) is False

    nossa = losses.loc["Nossa"]
    assert nossa["location_precision"] == "region"
    assert nossa["flag_at_loss_polity"] == "Portugal"
    assert bool(nossa["redistribute"]) is False

    dauphin = losses.loc["Dauphin"]
    assert dauphin["location_text"] == "Rio de Janeiro"
    assert dauphin["flag_at_loss_polity"] == "France"
    assert bool(dauphin["redistribute"]) is True

    events = extract.events.set_index("ship_name")
    harriet = events.loc["Harriet"]
    assert harriet["mechanism"] == "captured"
    assert harriet["to_polity"] == "Great Britain"
    assert harriet["captor"] == "British"
    assert "Antelope" in events.index


def _capture_payload() -> str:
    geometry = {
        "type": "FeatureCollection",
        "features": [
            {
                "type": "Feature",
                "geometry": {
                    "type": "Polygon",
                    "coordinates": [
                        [[0.0, 51.0], [1.0, 51.0], [1.0, 52.0], [0.0, 52.0], [0.0, 51.0]]
                    ],
                },
                "properties": {},
            }
        ],
    }
    return json.dumps(geometry)


def _write_prizepapers(root: Path) -> None:
    target = root / "prize-papers"
    target.mkdir(parents=True)
    (target / "ship_00000.json").write_text(
        json.dumps(
            {
                "docs": [
                    {
                        "PI": "prizepapers_ship_1",
                        "MD_SHIP_ALL_NAMES": ["Swift"],
                        "MD_SHIP_FORMER_NAMES": ["Old Swift"],
                        "MD_SHIP_RULING_AUTHORITY": ["Great Britain"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    (target / "capture_00000.json").write_text(
        json.dumps(
            {
                "docs": [
                    {
                        "PI": "prizepapers_capture_1",
                        "MD_CAPTURE_PLACE": "North Sea",
                        "MD_ALL_COORDS_FOR_SPATIALSEARCH": [_capture_payload()],
                        "MD_CAPTURE_DATE_CREATED_START": "1798-05-01",
                        "MD_CAPTURE_TYPE": "Seized at sea",
                        "MD_CAPTURE_DESCRIPTION": "Taken without a fight.",
                    },
                    {
                        "PI": "prizepapers_capture_2",
                        "MD_CAPTURE_PLACE": "The Channel",
                        "MD_ALL_COORDS_FOR_SPATIALSEARCH": [_capture_payload()],
                        "MD_CAPTURE_DATE_CREATED_START": "1800-01-01",
                        "MD_CAPTURE_DESCRIPTION": "The ship was sunk by the capturer.",
                    },
                    {
                        "PI": "prizepapers_capture_3",
                        "MD_CAPTURE_PLACE": "The Channel",
                        "MD_CAPTURE_DATE_CREATED_START": "1900-01-01",
                        "MD_CAPTURE_DESCRIPTION": "Taken safely.",
                    },
                ]
            }
        ),
        encoding="utf-8",
    )
    (target / "event_00000.json").write_text(
        json.dumps(
            {
                "docs": [
                    {
                        "PI": "prizepapers_event_1",
                        "PI_TOPSTRUCT": "prizepapers_ship_1",
                        "MD_EVENT_CAPTURE_LINK": "prizepapers_capture_2",
                        "MD_EVENT_RULING_AUTHORITY": ["Great Britain"],
                        "MD_EVENT_JOURNEY_TYPE": ["Journey interrupted by capture"],
                    }
                ]
            }
        ),
        encoding="utf-8",
    )


def test_prizepapers_captures_are_events_and_destruction_is_loss(tmp_path):
    _write_prizepapers(tmp_path)
    extract = prizepapers.extract(tmp_path)

    assert len(extract.events) == 2
    assert len(extract.losses) == 1
    events = extract.events.set_index("source_record_id")
    plain = events.loc["prizepapers_capture_1"]
    assert plain["mechanism"] == "captured"
    assert plain["place_text"] == "North Sea"
    assert plain["lat"] == pytest.approx(51.5)

    linked = events.loc["prizepapers_capture_2"]
    assert linked["ship_name"] == "Swift"
    assert linked["from_polity"] == "Great Britain"
    assert "prizepapers_capture_3" not in events.index

    loss = extract.losses.iloc[0]
    assert loss["source_record_id"] == "prizepapers_capture_2"
    assert loss["cause_class"] == "enemy_action"
    assert loss["ship_name"] == "Swift"
    assert loss["former_names"] == ["Old Swift"]


def _write_todoababor(root: Path) -> None:
    target = root / "todo-a-babor"
    target.mkdir(parents=True)
    (target / "article_01.html").write_text(
        """
        <html><body><article>
        <h2>Introducci\u00f3n</h2>
        <p>Intro text.</p>
        <h2>Nav\u00edos perdidos</h2>
        <h3>Destruidos</h3>
        <p>Incendiados por sus propias tripulaciones para evitar su apresamiento,
        durante la invasi\u00f3n brit\u00e1nica de la Isla Trinidad en 1797:</p>
        <ul><li>San Vicente (80)</li><li>Arrogante (74)</li></ul>
        <h3>Apresados por los brit\u00e1nicos</h3>
        <p>En la batalla del Cabo de San Vicente el 14 de febrero de 1797:</p>
        <ul><li>San Jos\u00e9 (112 ca\u00f1ones)</li></ul>
        <p>Entradas relacionadas:</p>
        <ul><li>Un enlace cualquiera</li></ul>
        </article></body></html>
        """,
        encoding="utf-8",
    )
    (target / "article_02.html").write_text(
        """
        <html><body><article>
        <p>1718</p>
        <ul>
        <li>HMS Ferret (bergant\u00edn)</li>
        <li>HMS Greyhound (fragata)</li>
        <li>Embarcaciones menores de guerra</li>
        </ul>
        </article></body></html>
        """,
        encoding="utf-8",
    )


def test_todoababor_splits_losses_from_captures(tmp_path):
    _write_todoababor(tmp_path)
    extract = todoababor.extract(tmp_path)

    assert len(extract.losses) == 2
    assert len(extract.events) == 3
    losses = extract.losses.set_index("ship_name")
    vicente = losses.loc["San Vicente"]
    assert vicente["cause_class"] == "scuttled"
    assert vicente["location_text"] == "Isla Trinidad"
    assert vicente["location_precision"] == "place"
    assert vicente["origin_polity"] == "Spain"

    events = extract.events.set_index("ship_name")
    jose = events.loc["San Jos\u00e9"]
    assert jose["mechanism"] == "captured"
    assert jose["from_polity"] == "Spain"
    assert jose["to_polity"] == "Great Britain"
    assert jose["place_text"] == "Cabo de San Vicente"
    assert jose["date"] == "1797-02-14"

    ferret = events.loc["HMS Ferret"]
    assert ferret["from_polity"] == "Great Britain"
    assert ferret["to_polity"] == "Spain"
    assert ferret["date"] == "1718"
    assert "Embarcaciones menores de guerra" not in events.index


def test_sv_codebook_parsers():
    pytest.importorskip("pypdf")
    module = _load_codebook()
    fate_lines = [
        "FATE  Particular outcome of voyage",
        "FATE 1",
        "Value Label",
        "2 Shipwrecked or destroyed, before slaves embarked",
        "10 Captured by British - before slaves embarked",
        "FATE2  Outcome of voyage for slaves",
    ]
    fate = module.parse_fate_entries(fate_lines)
    assert fate[2].startswith("Shipwrecked")
    assert fate[10].startswith("Captured by British")

    nation_lines = [
        "NATIONAL Country in which ship registered",
        "NATIONAL",
        "Value Label",
        "1 Spain",
        "13 Sweden",
        "TONNAGE Tonnage of vessel",
    ]
    nation = module.parse_nation_entries(nation_lines)
    assert nation[1] == "Spain"
    assert nation[13] == "Sweden"

    place_lines = [
        "Broad Regions",
        "10100 Spain",
        "10000 Europe 10400 England and Wales 10432 Liverpool",
        "34299 Barbados, place unspecified",
    ]
    places = module.parse_place_entries(place_lines)
    assert places["10432"] == "Liverpool"
    assert places["34299"] == "Barbados, place unspecified"

    fate_rows = {row["code"]: row for row in module.build_fate_rows(fate)}
    assert fate_rows[2]["is_loss"] == "true"
    assert fate_rows[10]["is_capture"] == "true"
    assert fate_rows[10]["captor_polity"] == "Great Britain"
    nation_rows = {row["code"]: row for row in module.build_nation_rows(nation)}
    assert nation_rows[13]["polity"] == "Sweden"


@pytest.mark.real_data
def test_golden_slavevoyages_counts():
    path = _raw("slavevoyages/tastdb-exp-2019.csv")
    with path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    assert len(rows) == 36108

    extract = slavevoyages.extract(RAW)
    assert len(extract.losses) == 1079
    assert len(extract.events) >= 1509


@pytest.mark.real_data
def test_golden_prizepapers_counts():
    summary_path = _raw("prize-papers/summary.json")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    assert summary["counts"]["ship"] == 4215
    assert summary["counts"]["capture"] == 2857

    extract = prizepapers.extract(RAW)
    assert len(extract.events) == 2856
    assert len(extract.losses) == 9
