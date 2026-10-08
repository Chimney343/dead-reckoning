"""Todo a Babor Spanish loss list and reverse capture list (plan section 2.3)."""

from __future__ import annotations

import re
from pathlib import Path

import pandas as pd
from lxml import html as lxml_html

from ..normalize import causes, dates
from ..schema import empty_events, empty_losses, event_row
from ..types import Extract
from .common import load_meta, losses_frame

ID = "todo-a-babor"

_PLACE_PATTERNS = (
    re.compile(
        r"batalla (?:de|del|en)\s+([^,.:;]+?)(?:\s+el\s+\d|\s+en\s+\d|,|\.|:|$)",
        re.IGNORECASE,
    ),
    re.compile(r"combate de\s+([^,.:;]+?)(?:\s+el\s+\d|,|\.|:|$)", re.IGNORECASE),
    re.compile(
        r"invasi[oó]n(?: brit[aá]nica)? de\s+([^,.:;]+?)(?:\s+en\s+\d|,|\.|:|$)",
        re.IGNORECASE,
    ),
    re.compile(r"\bEn\s+([A-Za-zÁÉÍÓÚÑáéíóúñ][^,.:;]*?)\s+en\s+\d{4}", re.UNICODE),
)
_YEAR = re.compile(r"\b(1[4-9]\d\d)\b")
_ES_DATE = re.compile(r"\d{1,2}\s+de\s+[a-záéíóúüñ]+\s+de\s+\d{4}", re.IGNORECASE)
_NAME = re.compile(r"^(?P<name>[^()]*?)\s*\((?P<paren>[^()]*)\)\s*(?P<tail>.*)$")


def _clean(value: object) -> str:
    return " ".join(str(value or "").split())


def _place_from_heading(text: str) -> str:
    for pattern in _PLACE_PATTERNS:
        match = pattern.search(text)
        if match:
            candidate = match[1].strip(" .:,;")
            candidate = re.sub(r"^(?:la|el|los|las)\s+", "", candidate, flags=re.IGNORECASE)
            if candidate and not any(char.isdigit() for char in candidate):
                return candidate
    return ""


def _parse_date(text: str):
    parsed = dates.parse_date(text)
    if parsed:
        return parsed
    spanish = _ES_DATE.search(text)
    if spanish:
        return dates.parse_date(spanish.group(0))
    match = _YEAR.search(text)
    if match:
        return dates.parse_date(match.group(1))
    return None


def _split_name(text: str) -> tuple[str, str]:
    match = _NAME.match(text)
    if match:
        return (match["name"].strip(" .,;"), match["paren"].strip())
    return (text.strip(" .,;"), "")


def _is_noise(name: str, paren: str) -> bool:
    if not name:
        return True
    return not paren and "hms" not in name.casefold()


def _article_elements(path: Path) -> list:
    tree = lxml_html.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    articles = tree.xpath("//article")
    root = articles[0] if articles else tree
    return list(root.iter())


def _extract_article(path: Path, article: str, meta: dict) -> tuple[list[dict], list[dict]]:
    if not path.exists():
        return ([], [])
    elements = _article_elements(path)
    start = 0
    for index, element in enumerate(elements):
        text = _clean(element.text_content()).casefold()
        if element.tag in {"h2", "h3"} and "introducci" in text:
            start = index + 1
            break

    losses: list[dict] = []
    events: list[dict] = []
    section = ""
    detail = ""
    counter = 0
    for element in elements[start:]:
        tag = element.tag
        if tag in {"h2", "h3"}:
            section = _clean(element.text_content())
            detail = ""
            continue
        if tag == "p":
            text = _clean(element.text_content())
            if "entradas relacionadas" in text.casefold():
                break
            detail = text
            continue
        if tag != "ul":
            continue
        heading = " ".join(part for part in (section, detail) if part)
        if not heading:
            continue
        is_capture = article == "article_02" or "apresad" in heading.casefold()
        location = _place_from_heading(heading)
        location_precision = "place" if location else "none"
        cause = causes.classify(heading)
        if is_capture:
            if "brit" in heading.casefold():
                to_polity, captor = "Great Britain", "Great Britain"
            else:
                to_polity, captor = "Spain", "Spain"
            from_polity = "Spain" if article == "article_01" else "Great Britain"
        for item in element.xpath("./li"):
            text = _clean(item.text_content())
            if not text:
                continue
            name, paren = _split_name(text)
            if _is_noise(name, paren):
                continue
            parsed = _parse_date(text) or _parse_date(detail) or _parse_date(heading)
            record_id = f"{article}:{counter}"
            counter += 1
            raw = {"article": article, "heading": heading, "entry": text}
            if is_capture:
                events.append(
                    {
                        "source": meta["source"],
                        "source_record_id": record_id,
                        "ship_name": name,
                        "date": parsed.iso if parsed else None,
                        "date_precision": parsed.precision if parsed else "none",
                        "from_polity": from_polity,
                        "to_polity": to_polity,
                        "mechanism": "captured",
                        "captor": captor,
                        "place_text": location or None,
                        "location_precision": location_precision,
                        "raw": raw,
                    }
                )
            else:
                losses.append(
                    {
                        "source": meta["source"],
                        "source_record_id": record_id,
                        "source_url": meta["source_url"],
                        "tier": meta["tier"],
                        "licence": meta["licence"],
                        "redistribute": meta["redistribute"],
                        "ship_name": name,
                        "ship_type": paren if paren and not paren[0].isdigit() else None,
                        "loss_date": parsed.iso if parsed else None,
                        "loss_year": parsed.year if parsed else None,
                        "date_precision": parsed.precision if parsed else "none",
                        "location_text": location or None,
                        "location_precision": location_precision,
                        "geocode_method": "none",
                        "origin_raw": "Spain",
                        "origin_polity": "Spain",
                        "origin_basis": "flag_assumed",
                        "flag_at_loss_raw": "Spain",
                        "flag_at_loss_polity": "Spain",
                        "cause_raw": heading or None,
                        "cause_class": cause.cause_class,
                        "weather_related": cause.weather_related,
                        "is_total_loss": cause.is_total_loss,
                        "raw": raw,
                    }
                )
    return (losses, events)


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "todo-a-babor"
    first_article = (directory / "article_01.html").exists()
    second_article = (directory / "article_02.html").exists()
    if not first_article and not second_article:
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T2",
        licence="None stated",
        redistribute=False,
        url="https://www.todoababor.es/",
    )
    loss_rows: list[dict] = []
    event_rows: list[dict] = []
    for article in ("article_01", "article_02"):
        article_losses, article_events = _extract_article(
            directory / f"{article}.html", article, meta
        )
        loss_rows.extend(article_losses)
        event_rows.extend(article_events)

    losses = losses_frame(loss_rows) if loss_rows else empty_losses()
    events = (
        pd.DataFrame([event_row(**row) for row in event_rows]) if event_rows else empty_events()
    )
    return Extract(losses=losses, events=events)
