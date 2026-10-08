"""Wikipedia yearly shipwreck lists (plan sections 2.2 and 5).

One JSON file per page under ``data/raw/wikipedia/en-shipwrecks/<title>.json``
with keys ``title``, ``revid``, ``wikitext``, ``html`` and ``url``. The page has
an h2 per month, an h3 per day and a wikitable per section with the columns
``Ship | State | Description``.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pandas as pd
from lxml import html as lxml_html

from ..normalize import causes, coords, dates, places, polities
from ..schema import empty_events, empty_losses, event_row
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "wp-en-shipwrecks"

_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
}
_YEAR = re.compile(r"(\d{4})")
_DAY = re.compile(r"(\d{1,2})")
_CAPTURE = re.compile(
    r"captured[^.]*?\bby\s+(?:a\s+|an\s+|the\s+)?([A-Z][A-Za-z' -]+)", re.IGNORECASE
)
_WIKITEXT_COORD = re.compile(r"\{\{\s*coord\s*\|\s*(-?\d+(?:\.\d+)?)\s*\|\s*(-?\d+(?:\.\d+)?)")


def _month(text: str) -> int | None:
    lowered = text.casefold()
    for name, number in _MONTHS.items():
        if name in lowered:
            return number
    return None


def _cell_text(cell) -> str:
    return " ".join(cell.text_content().split()).strip()


def _first_link(cell) -> str:
    for text in cell.xpath(".//a/text()"):
        cleaned = text.strip()
        if cleaned:
            return cleaned
    return _cell_text(cell)


def _row_coordinates(row) -> tuple[float, float] | None:
    for text in row.xpath('.//span[contains(@class, "geo")]/text()'):
        pair = coords.parse_zenodo_coordinates(text)
        if pair:
            return pair
    return None


def _parse_page(path: Path) -> tuple[list[dict], list[dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    title = first(payload.get("title")) or path.stem
    url = first(payload.get("url"))
    year_match = _YEAR.search(title)
    year = int(year_match.group(1)) if year_match else None
    html_text = first(payload.get("html")) or ""
    wikitext = first(payload.get("wikitext")) or ""
    document = lxml_html.fromstring(html_text or "<html></html>")

    rows: list[dict] = []
    events: list[dict] = []
    month = day = None
    row_index = 0
    for element in document.iter():
        tag = element.tag if isinstance(element.tag, str) else ""
        if tag == "h2":
            month = _month(element.text_content())
        elif tag == "h3":
            day_match = _DAY.search(element.text_content())
            day = int(day_match.group(1)) if day_match else None
            month = _month(element.text_content()) or month
        elif tag == "table" and "wikitable" in (element.get("class") or ""):
            for table_row in element.xpath(".//tr"):
                cells = table_row.xpath("./th|./td")
                if len(cells) < 3:
                    continue
                if cells[0].tag == "th":
                    continue
                ship_name = _cell_text(cells[0])
                if not ship_name:
                    continue
                row_index += 1
                state = _first_link(cells[1])
                description = _cell_text(cells[2])
                polity = polities.lookup(state) if state else None
                pair = _row_coordinates(table_row)
                if pair is None and wikitext:
                    coord_match = _WIKITEXT_COORD.search(wikitext)
                    if coord_match:
                        pair = (float(coord_match.group(1)), float(coord_match.group(2)))
                parsed = None
                if year:
                    if month and day:
                        parsed = dates.parse_date(f"{year:04d}-{month:02d}-{day:02d}")
                    elif month:
                        parsed = dates.parse_date(f"{year:04d}-{month:02d}")
                    else:
                        parsed = dates.parse_date(str(year))
                cause = causes.classify(description)
                place = places.extract_place(description)
                record_id = f"{title}:{row_index}"
                rows.append(
                    {
                        "source": ID,
                        "source_record_id": record_id,
                        "source_url": url or None,
                        "tier": "T3",
                        "licence": "CC-BY-SA-4.0",
                        "redistribute": True,
                        "ship_name": ship_name,
                        "loss_date": parsed.iso if parsed else None,
                        "loss_year": parsed.year if parsed else year,
                        "date_precision": parsed.precision if parsed else "none",
                        "lat": pair[0] if pair else None,
                        "lon": pair[1] if pair else None,
                        "location_text": place,
                        "location_precision": "reported" if pair else "place"
                        if place
                        else "none",
                        "uncertainty_km": 5.0 if pair else (10.0 if place else None),
                        "geocode_method": "source_coords" if pair else "none",
                        "origin_raw": None,
                        "origin_polity": polity[0] if polity else None,
                        "origin_basis": "flag_assumed" if polity else None,
                        "flag_at_loss_raw": state,
                        "flag_at_loss_polity": polity[0] if polity else None,
                        "cause_raw": description or None,
                        "cause_class": cause.cause_class,
                        "weather_related": cause.weather_related,
                        "is_total_loss": cause.is_total_loss,
                        "raw": {"title": title, "state": state, "description": description},
                    }
                )
                capture = _CAPTURE.search(description)
                if capture:
                    captor_text = capture.group(1).strip()
                    captor = polities.lookup(captor_text) or polities.lookup(
                        captor_text.split()[0]
                    )
                    events.append(
                        event_row(
                            source=ID,
                            source_record_id=f"{record_id}:capture",
                            ship_name=ship_name,
                            date=parsed.iso if parsed else None,
                            mechanism="captured",
                            from_polity=polity[0] if polity else None,
                            to_polity=captor[0] if captor else None,
                            captor=captor[0] if captor else None,
                            place_text=place,
                            raw={"description": description},
                        )
                    )
    return rows, events


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "wikipedia" / "en-shipwrecks"
    if not directory.exists():
        return Extract(empty_losses(), empty_events())
    meta = load_meta(directory, ID, tier="T3", licence="CC-BY-SA-4.0", redistribute=True)
    rows: list[dict] = []
    events: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        page_rows, page_events = _parse_page(path)
        rows.extend(page_rows)
        events.extend(page_events)
    _ = meta
    return Extract(
        losses=losses_frame(rows) if rows else empty_losses(),
        events=pd.DataFrame(events) if events else empty_events(),
    )
