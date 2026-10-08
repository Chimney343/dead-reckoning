"""parsing/common.py: the text and link helpers shared by every page parser."""

from __future__ import annotations

from parsel import Selector
from threedecks.parsing import common

TOOLTIP_CELL = """
<td class="column2">
  <span class="hidden">Name : </span>
  <div class="tooltip">
    <a href="index.php?display_type=show_ship&amp;id=2657">Neptuno (80)</a>
    <span class="tooltiptext">1795-1805<br>Spanish 80 Gun<br>3rd Rate Ship of the Line</span>
  </div>
  <a href="index.php?display_type=show_shipyard&amp;id=95">Le Havre</a>
</td>
"""


def sel(html: str) -> Selector:
    return Selector(text=html)


def test_visible_text_excludes_the_tooltip_card():
    cell = sel(TOOLTIP_CELL).xpath("//td")
    assert common.visible_text(cell) == "Name : Neptuno (80) Le Havre"


def test_visible_text_can_drop_the_hidden_prefix():
    cell = sel(TOOLTIP_CELL).xpath("//td")
    assert common.visible_text(cell, drop_hidden=True) == "Neptuno (80) Le Havre"


def test_link_ids_match_the_kind_exactly():
    cell = sel(TOOLTIP_CELL).xpath("//td")
    assert common.link_ids(cell, "show_ship") == [2657]
    assert common.link_ids(cell, "show_shipyard") == [95]


def test_links_excludes_tooltip_links_and_keeps_the_card():
    cell = sel(TOOLTIP_CELL).xpath("//td")
    links = common.links(cell)
    assert [link.kind for link in links] == ["show_ship", "show_shipyard"]
    assert links[0].tooltip == [
        "1795-1805",
        "Spanish 80 Gun",
        "3rd Rate Ship of the Line",
    ]


def test_has_footer_requires_the_copyright_span():
    with_footer = sel('<html><body><span id="copywrite_message">Copyright &copy; C</span>'
                      "</body></html>")
    without_footer = sel("<html><body><div id='datacol'></div></body></html>")
    assert common.has_footer(with_footer) is True
    assert common.has_footer(without_footer) is False
