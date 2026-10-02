"""Layer 2: the ``<br>``-delimited span grids and heading-based sections."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.grid import (
    heading_text,
    section_by_heading,
    span_rows,
    strip_count,
)

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


@pytest.fixture
def scope():
    return Selector((FIXTURES / "grid.html").read_text(encoding="utf-8"))


def row_text(row):
    texts: list[str] = []
    for node in row:
        texts.extend(node.xpath(".//text()").getall())
    return re.sub(r"\s+", " ", " ".join(texts)).strip()


def test_strip_count_removes_leading_number():
    assert strip_count("15 Ship Commanders") == "Ship Commanders"
    assert strip_count("1 Commissioned Officer") == "Commissioned Officer"
    assert strip_count("Dimensions") == "Dimensions"


def test_heading_text_keeps_full_heading(scope):
    h2 = scope.xpath("//h2[contains(., 'Ship Commanders')]")[0]
    assert heading_text(h2) == "15 Ship Commanders"


def test_section_by_heading_missing_returns_none(scope):
    assert section_by_heading(scope, "Nonexistent") is None


def test_dimensions_split_into_rows(scope):
    section = section_by_heading(scope, "Dimensions")
    rows = span_rows(section)
    assert len(rows) == 5
    assert "B006" in row_text(rows[0])
    assert row_text(rows[1]).startswith("Length of Gundeck")
    assert "190' 0\"" in row_text(rows[1])
    assert row_text(rows[3]).startswith("Dimension")
    assert "AGMAB" in row_text(rows[3])


def test_service_history_does_not_bleed_into_crew_complement(scope):
    # Both sections live under div#ship_complement: selecting by id is wrong.
    section = section_by_heading(scope, "Service History")
    rows = span_rows(section)
    assert len(rows) == 2
    assert "505" not in " ".join(row_text(r) for r in rows)
    assert "Left Cartagena" in row_text(rows[0])


def test_officer_section_stops_at_next_heading(scope):
    section = section_by_heading(scope, "Ship Commanders")
    rows = span_rows(section)
    assert len(rows) == 2  # header row + one officer
    assert "Capitán de navío" in row_text(rows[1])


def test_armament_rows_survive_td_inside_span(scope):
    section = section_by_heading(scope, "Armament")
    rows = span_rows(section)
    joined = [row_text(r) for r in rows]
    assert any("28 Spanish 24-Pounder" in t for t in joined)
    assert any("Lower Gun Deck" in t for t in joined)
    assert any("SWoA" in t for t in joined)
