"""Schema and Extract contract tests (plan sections 3 and 4)."""

from __future__ import annotations

import pandas as pd
from shiplosses import registry, schema


def test_empty_losses_has_exact_columns_and_defaults():
    df = schema.empty_losses()
    assert list(df.columns) == schema.LOSS_COLUMNS
    assert df.empty


def test_loss_row_fills_defaults_and_builds_id():
    row = schema.loss_row(source="ukho-wrecks", source_record_id="42", ship_name="HMS Victory")
    assert row["loss_id"] == "ukho-wrecks:42"
    assert row["ship_name_norm"] == "victory"
    assert row["is_total_loss"] is True
    assert row["redistribute"] is True
    assert row["former_names"] == []
    df = pd.DataFrame([row])
    assert schema.validate_losses(df) == []


def test_validate_losses_flags_bad_enum_and_coordinate():
    row = schema.loss_row(
        source="x",
        source_record_id="1",
        cause_class="exploded",
        location_precision="vague",
        lat=999.0,
        lon=0.0,
    )
    problems = schema.validate_losses(pd.DataFrame([row]))
    assert any("cause_class" in p for p in problems)
    assert any("location_precision" in p for p in problems)
    assert any("lat" in p for p in problems)


def test_validate_losses_flags_duplicate_ids():
    a = schema.loss_row(source="x", source_record_id="1")
    problems = schema.validate_losses(pd.DataFrame([a, dict(a)]))
    assert any("duplicate" in p for p in problems)


def test_extract_dataclass_and_registry_lookup():
    extract = registry.Extract(losses=schema.empty_losses(), events=schema.empty_events())
    assert extract.losses.empty and extract.events.empty
    ids = {module.ID for module in registry.SOURCES}
    # Core, coordinate-rich sources must be registered from the first phase.
    assert {"ukho-wrecks", "wa-shipwrecks", "zenodo-shipwrecks"} <= ids
