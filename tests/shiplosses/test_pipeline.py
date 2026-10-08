"""Pipeline tests: geocoding, ownership and de-duplication (plan sections 5.6, 6, 10)."""

from __future__ import annotations

import pandas as pd
import pytest
from shiplosses import dedupe, geocode, ownership
from shiplosses.schema import event_row, loss_row
from shiplosses.sources.common import losses_frame


def test_geocode_uses_override(tmp_path):
    (tmp_path / "place_overrides.csv").write_text(
        "location_text,source,lat,lon,precision,note\n"
        "off Barmouth,*,52.7,-4.1,place,\n",
        encoding="utf-8",
    )
    losses = losses_frame(
        [loss_row(source="wa-shipwrecks", source_record_id="1", location_text="off Barmouth")]
    )
    gaz = geocode.Gazetteers(tmp_path, tmp_path / "raw")
    unresolved: dict[str, int] = {}
    result = geocode.geocode_losses(losses, gaz, unresolved=unresolved)
    row = result.iloc[0]
    assert row["lat"] == pytest.approx(52.7)
    assert row["lon"] == pytest.approx(-4.1)
    assert row["location_precision"] == "place"
    assert row["geocode_method"] == "override"
    assert unresolved == {}


def test_geocode_records_unresolved(tmp_path):
    losses = losses_frame(
        [loss_row(source="zenodo-shipwrecks", source_record_id="1", location_text="Nowhere")]
    )
    gaz = geocode.Gazetteers(tmp_path, tmp_path / "raw")
    unresolved: dict[str, int] = {}
    geocode.geocode_losses(losses, gaz, unresolved=unresolved)
    assert unresolved == {"Nowhere": 1}


def test_ownership_matches_event_to_loss():
    losses = losses_frame(
        [
            loss_row(
                source="zenodo-shipwrecks",
                source_record_id="1",
                ship_name="Mary",
                loss_year=1797,
                flag_at_loss_polity="France",
            )
        ]
    )
    events = pd.DataFrame(
        [
            event_row(
                source="prize-papers",
                source_record_id="cap1",
                ship_name="Mary",
                date="1795",
                mechanism="captured",
                from_polity="Great Britain",
                to_polity="France",
            )
        ]
    )
    result = ownership.resolve(losses, events)
    row = result.iloc[0]
    assert row["owner_at_loss"] == "France"
    assert bool(row["ownership_changed"]) is True
    assert "prize-papers" in row["ownership_change"]


def test_dedupe_deterministic_wiid_cluster():
    losses = losses_frame(
        [
            loss_row(
                source="ireland-wiid",
                source_record_id="W00001",
                ship_name="Actur",
                raw={"Wreck No": "W00001"},
            ),
            loss_row(
                source="ireland-infomar",
                source_record_id="W00001",
                ship_name="Actur",
                lat=54.0,
                lon=-6.0,
                location_precision="surveyed",
                raw={"nms_ref": "W00001"},
            ),
            loss_row(
                source="emodnet-shipwrecks",
                source_record_id="2",
                ship_name="Actur",
                lat=54.05,
                lon=-6.05,
                location_precision="reported",
                raw={"source_id": "W00001"},
            ),
        ]
    )
    result = dedupe.dedupe(losses)
    assert result["cluster_id"].nunique() == 1
    assert result["is_primary"].sum() == 1
    primary = result[result["is_primary"]].iloc[0]
    assert primary["source"] == "ireland-infomar"


def test_dedupe_keeps_different_ships_apart():
    losses = losses_frame(
        [
            loss_row(
                source="zenodo-shipwrecks",
                source_record_id="1",
                ship_name="Mary",
                loss_year=1797,
                lat=10.0,
                lon=10.0,
            ),
            loss_row(
                source="novascotia-shipwrecks",
                source_record_id="2",
                ship_name="Mary",
                loss_year=1798,
                lat=-40.0,
                lon=-60.0,
            ),
        ]
    )
    result = dedupe.dedupe(losses)
    assert result["cluster_id"].nunique() == 2
    assert result["is_primary"].sum() == 2
