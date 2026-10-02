"""Layer 2: the ship-search results parser."""

from __future__ import annotations

from pathlib import Path

from parsel import Selector
from threedecks.parsing.search import parse_search

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def load(name):
    return Selector((FIXTURES / name).read_text(encoding="utf-8"))


def test_page1_ids_total_and_next():
    result = parse_search(load("search_page1.html"))
    assert result.ship_ids == [16801, 16802, 16803]
    assert result.total == 1863
    assert result.page == 1
    assert result.pages == 38
    assert result.has_next is True


def test_alternate_name_row_yields_one_id():
    # A "(R)" row links both names; only the first is the ship's own id.
    result = parse_search(load("search_page1.html"))
    assert result.ship_ids.count(16803) == 1
    assert 16999 not in result.ship_ids


def test_last_page_has_no_next():
    result = parse_search(load("search_page2.html"))
    assert result.ship_ids == [17000]
    assert result.has_next is False


def test_empty_page():
    result = parse_search(load("search_empty.html"))
    assert result.ship_ids == []
    assert result.total == 0
    assert result.has_next is False


def test_not_found_page_has_no_ids():
    result = parse_search(load("notfound.html"))
    assert result.ship_ids == []
    assert result.total is None
    assert result.has_next is False
