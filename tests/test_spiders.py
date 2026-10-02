"""Layer 4: spider behaviour, offline against synthetic fixtures (Plan 6)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs

from scrapy.http import FormRequest, HtmlResponse, Request
from threedecks.items import CaptureRow
from threedecks.spiders.captures import CapturesSpider
from threedecks.spiders.ships_all import ShipsAllSpider
from threedecks.spiders.ships_by_nation import ShipsByNationSpider

FIXTURES = Path(__file__).parent / "fixtures" / "synthetic"


def response_for(
    name, url="https://threedecks.org/index.php?display_type=x", status=200, meta=None
):
    body = (FIXTURES / name).read_bytes()
    request = Request(url, meta=meta or {})
    return HtmlResponse(url=url, body=body, encoding="utf-8", status=status, request=request)


def make(spider_cls, tmp_path, **kwargs):
    spider = spider_cls(
        name=spider_cls.name, base_url="http://local", data_dir=str(tmp_path), **kwargs
    )
    return spider


# --- captures --------------------------------------------------------------


def test_captures_issues_one_form_post(tmp_path):
    spider = make(CapturesSpider, tmp_path)
    requests = list(spider.start_requests())
    spider.closed("test")
    assert len(requests) == 1
    assert isinstance(requests[0], FormRequest)
    assert requests[0].method == "POST"
    data = parse_qs(requests[0].body.decode())
    assert data["select_from_nation"] == ["7"]
    assert data["select_by_nation"] == ["1"]
    assert data["select_captures"] == ["Change Filter"]


def test_captures_parse_yields_rows_and_unique_ship_requests(tmp_path):
    spider = make(CapturesSpider, tmp_path)
    response = response_for("captures.html", "https://threedecks.org/index.php?display_type=select_capture")
    produced = list(spider.parse_captures(response))
    spider.closed("test")

    rows = [p for p in produced if isinstance(p, CaptureRow)]
    requests = [p for p in produced if isinstance(p, Request)]
    assert len(rows) == 4
    ids = [int(r.url.split("id=")[1]) for r in requests]
    assert sorted(ids) == [6420, 13716, 21635, 24577]


# --- incarnation following -------------------------------------------------


def test_incarnation_following_at_depth_zero(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    followed = sorted(int(r.url.split("id=")[1]) for r in requests)
    assert followed == [50, 60]


def test_incarnation_following_stops_at_max_depth(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 1},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    assert [p for p in produced if isinstance(p, Request)] == []


def test_sidebar_links_are_not_followed(tmp_path):
    spider = make(ShipsAllSpider, tmp_path, max_depth=1)
    response = response_for(
        "ship_full.html",
        "https://threedecks.org/index.php?display_type=show_ship&id=1234",
        meta={"depth": 0},
    )
    produced = list(spider.parse_ship_page(response))
    spider.closed("test")
    followed = {int(r.url.split("id=")[1]) for r in produced if isinstance(r, Request)}
    assert 9999 not in followed and 7777 not in followed and 8888 not in followed


# --- search pagination -----------------------------------------------------


def test_search_pagination_requests_next_page(tmp_path):
    spider = make(ShipsByNationSpider, tmp_path)
    produced = list(spider.parse_search(response_for("search_page1.html")))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    ship_ids = sorted(int(r.url.split("id=")[1]) for r in requests if "show_ship" in r.url)
    next_pages = [r for r in requests if "ships_search" in r.url]
    assert ship_ids == [16801, 16802, 16803]
    assert len(next_pages) == 1
    assert parse_qs(next_pages[0].body.decode())["page"] == ["2"]


def test_search_last_page_stops(tmp_path):
    spider = make(ShipsByNationSpider, tmp_path)
    produced = list(spider.parse_search(response_for("search_page2.html")))
    spider.closed("test")
    requests = [p for p in produced if isinstance(p, Request)]
    assert [r for r in requests if "ships_search" in r.url] == []
    assert sorted(int(r.url.split("id=")[1]) for r in requests) == [17000]


# --- seeding ---------------------------------------------------------------


SITEMAP = b"""<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=10</loc></url>
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=12</loc></url>
  <url><loc>https://threedecks.org/index.php?display_type=show_ship&amp;id=14</loc></url>
</urlset>
"""


def test_sitemap_seeding_is_idempotent(tmp_path):
    spider = make(ShipsAllSpider, tmp_path)
    response = HtmlResponse(url="https://threedecks.org/ships.xml", body=SITEMAP, encoding="utf-8")

    first = list(spider.parse_sitemap(response))
    first_ids = sorted(int(r.url.split("id=")[1]) for r in first if isinstance(r, Request))
    # 10, 12, 14 from the sitemap, gaps 1..9/11/13, then the upward probe at 15.
    assert set(first_ids) == set(range(1, 15)) | {15}
    assert spider.store.counts_by_status() == {"pending": 15}

    list(spider.parse_sitemap(response))
    counts = spider.store.counts_by_status()
    spider.closed("test")
    # The second pass re-seeds nothing; only the upward probe advances (16).
    assert counts == {"pending": 16}


def test_trailing_not_found_counts_streak(tmp_path):
    from threedecks.state import StateStore

    store = StateStore(tmp_path / "state.sqlite")
    store.seed([1, 2, 3, 4], discovered_by="test")
    store.mark_status(2, "not_found")
    store.mark_status(3, "not_found")
    store.mark_status(4, "not_found")
    assert store.trailing_not_found() == 3
    store.mark_status(4, "done")
    assert store.trailing_not_found() == 0
    store.close()
