"""Three Decks ship-catalogue scraper.

A Scrapy project. Crawling and parsing are deliberately separated:
``threedecks.parsing`` holds pure ``(html, url) -> dataclass`` functions with
no Scrapy imports, while ``threedecks.spiders`` only builds requests and calls
those functions. Progress lives in ``data/threedecks/state.sqlite`` so a
cancelled or crashed run resumes from where it stopped.
"""

PARSER_VERSION = "4"
