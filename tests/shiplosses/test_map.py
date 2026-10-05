"""Interactive map test on a 50-row fixture (plan section 10)."""

from __future__ import annotations

import json

from shiplosses.mapping import interactive
from shiplosses.schema import loss_row
from shiplosses.sources.common import losses_frame

CAUSES = list(interactive.CAUSE_ORDER)


def _fixture() -> object:
    rows = []
    for index in range(50):
        rows.append(
            loss_row(
                source="fixture",
                source_record_id=str(index),
                ship_name=f"Ship {index}",
                loss_year=1500 + index * 5,
                lat=-40 + index,
                lon=-100 + index * 3,
                location_precision="reported",
                cause_class=CAUSES[index % len(CAUSES)],
                is_primary=True,
                cluster_id=f"c{index}",
            )
        )
    return losses_frame(rows)


def test_map_build_from_fixture(tmp_path):
    losses = _fixture()
    output = tmp_path / "map.html"
    interactive.build(losses, output, build_date="2026-01-01T00:00:00Z")
    html = output.read_text(encoding="utf-8")
    assert output.stat().st_size < 15 * 1024 * 1024
    assert "const RAW = [" in html
    assert "Ship 0" in html
    for cause in CAUSES:
        assert cause in html
    assert "NaN" not in html
    assert "Infinity" not in html


def test_map_data_roundtrips(tmp_path):
    losses = _fixture()
    output = tmp_path / "map.html"
    interactive.build(losses, output, build_date="2026-01-01T00:00:00Z")
    html = output.read_text(encoding="utf-8")
    start = html.index("const RAW = ") + len("const RAW = ")
    end = html.index(";\n", start)
    data = json.loads(html[start:end])
    assert len(data) == 50
    assert all(len(feature) == 18 for feature in data)
