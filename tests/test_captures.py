"""Layer 2: the captures list parser."""

from __future__ import annotations

from pathlib import Path

import pytest
from parsel import Selector
from threedecks.parsing.captures import parse_capture_nations, parse_captures

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"
QUERY = {"from_nation_id": 7, "by_nation_id": 1, "war_id": None}


def test_parses_the_taken_from_nations_from_the_form():
    selector = Selector((FIXTURES / "captures_form.html").read_text(encoding="utf-8"))
    assert parse_capture_nations(selector) == [7, 1, 4]  # placeholder 0 dropped


@pytest.fixture
def rows():
    selector = Selector((FIXTURES / "captures.html").read_text(encoding="utf-8"))
    return parse_captures(selector, QUERY)


def test_parses_every_data_row():
    selector = Selector((FIXTURES / "captures.html").read_text(encoding="utf-8"))
    assert len(parse_captures(selector, QUERY)) == 4


def test_normal_row(rows):
    row = rows[0]
    assert row.date.iso == "1704-04-16"
    assert row.date.tooltip == "16th of April 1704"
    assert row.captured_td_id == 24577
    assert row.captured_label == "Nuestra Señora del Rosario (25)"
    assert row.captor_td_ids == [13716]
    assert row.place_text == "The English Channel"
    assert row.from_nation_id == 7 and row.by_nation_id == 1 and row.war_id is None


def test_row_without_captor_link(rows):
    row = rows[1]
    assert row.captured_td_id == 21635
    assert row.captor_td_ids == []
    assert "Taken by the British" in row.captor_text
    assert row.place_text is None


def test_bef_date(rows):
    row = rows[2]
    assert row.date.qualifier == "bef."
    assert row.date.iso == "1718"
    assert row.date.precision == "year"


def test_row_without_captured_link(rows):
    row = rows[3]
    assert row.captured_td_id is None
    assert "Rodney" in row.captured_label
    assert row.date.iso == "1780-01-08"
