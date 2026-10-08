"""SlaveVoyages Trans-Atlantic export (plan section 2.2).

The loss/capture decision and the voyage stage come from the reviewed
``data/sv/fate.csv`` table; place codes resolve through ``data/sv/places.csv``
and ``NATIONAL`` through ``data/sv/nation.csv``.
"""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

import pandas as pd

from ..normalize import causes, dates, polities
from ..schema import empty_events, empty_losses, event_row
from ..types import Extract
from .common import first, load_meta, losses_frame

ID = "slavevoyages"

_DATA = Path(__file__).resolve().parents[2] / "data" / "sv"

_FATE3 = {
    "1": ("", "natural hazard"),
    "2": ("", "pirate/privateer"),
    "3": ("Great Britain", "British"),
    "4": ("Spain", "Spanish"),
    "5": ("Netherlands", "Dutch"),
    "6": ("Portugal", "Portuguese"),
    "8": ("France", "French"),
    "9": ("United States", "US"),
    "10": ("", "African"),
    "11": ("", "crew"),
    "12": ("Brazil", "Brazil"),
    "13": ("", "captor unspecified"),
    "14": ("", "not captured"),
    "15": ("", "unknown"),
    "16": ("", "Haitians"),
    "17": ("Venezuela", "Venezuelan"),
    "18": ("Sweden", "Swedish"),
}

_OWNER_COLUMNS = [f"OWNER{letter}" for letter in "ABCDEFGHIJKLMNOP"]

_COURT_WORDS = (
    "court",
    "proceeding",
    "condemned",
    "restored",
    "captured",
    "given up",
    "detained",
    "seized",
    "arrested",
)


def _is_court_change(label: str, code: int | None) -> bool:
    """Court and proceeding codes change ownership; 'no further record' does not."""
    if code is not None and code < 102:
        return False
    lowered = label.casefold()
    return any(word in lowered for word in _COURT_WORDS)


def _read_table(name: str) -> dict[str, dict[str, str]]:
    table: dict[str, dict[str, str]] = {}
    path = _DATA / name
    if not path.exists():
        return table
    with path.open(encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            code = (row.get("code") or "").strip()
            if code:
                table[code] = {key: (value or "").strip() for key, value in row.items()}
    return table


@lru_cache(maxsize=1)
def _fate() -> dict[str, dict[str, str]]:
    return _read_table("fate.csv")


@lru_cache(maxsize=1)
def _nations() -> dict[str, dict[str, str]]:
    return _read_table("nation.csv")


@lru_cache(maxsize=1)
def _places() -> dict[str, dict[str, str]]:
    return _read_table("places.csv")


def _truthy(value: object) -> bool:
    return str(value).strip().casefold() in {"true", "1", "yes"}


def _code_int(value: object) -> int | None:
    text = first(value)
    try:
        return int(text)
    except (TypeError, ValueError):
        return None


def _polity_for_national(code: str) -> tuple[str, str]:
    entry = _nations().get(code)
    if not entry:
        return ("", "")
    label = entry.get("label", "")
    mapped = polities.lookup(label)
    polity = mapped[0] if mapped else entry.get("polity", "")
    return (label, polity)


def _location(row: dict, stage: str) -> tuple[str, str, float | None, bool]:
    if stage == "before_embarkation":
        code = first(row.get("MJBYPTIMP")) or first(row.get("PLAC1TRA"))
        imputed = bool(first(row.get("MJBYPTIMP")))
    elif stage == "after_embarkation":
        code = first(row.get("MJBYPTIMP")) or first(row.get("PLAC1TRA"))
        imputed = bool(first(row.get("MJBYPTIMP")))
    elif stage == "after_disembarkation":
        code = first(row.get("SLA1PORT")) or first(row.get("MJSLPTIMP"))
        imputed = not first(row.get("SLA1PORT"))
    else:
        return ("", "none", None, False)
    if not code:
        return ("", "none", None, False)
    entry = _places().get(str(code))
    label = entry.get("label", "") if entry else ""
    region = str(code).endswith("99")
    return (label, "region" if region else "place", 250.0 if region else 10.0, imputed)


def extract(raw_root: Path) -> Extract:
    directory = raw_root / "slavevoyages"
    path = directory / "tastdb-exp-2019.csv"
    if not path.exists():
        return Extract(empty_losses(), empty_events())

    meta = load_meta(
        directory,
        ID,
        tier="T1",
        licence="Public domain; imputed fields CC-BY-NC-3.0-US",
        redistribute=False,
        url="https://www.slavevoyages.org/",
    )
    frame = pd.read_csv(path, dtype=str, keep_default_na=False, low_memory=False)

    loss_rows: list[dict] = []
    event_rows: list[dict] = []
    for index, record in enumerate(frame.to_dict("records")):
        record_id = first(record.get("VOYAGEID")) or str(index)
        fate_code = first(record.get("FATE"))
        fate_entry = _fate().get(fate_code)
        is_loss = bool(fate_entry) and _truthy(fate_entry.get("is_loss"))
        is_capture = bool(fate_entry) and _truthy(fate_entry.get("is_capture"))
        fate_int = _code_int(fate_code)
        if not is_loss and not is_capture and not _is_court_change(
            fate_entry.get("label", "") if fate_entry else "", fate_int
        ):
            continue

        ship_name = first(record.get("SHIPNAME")) or None
        rig = first(record.get("RIG")) or None
        parsed = dates.parse_date(record.get("YEARAM"))
        national_label, national_polity = _polity_for_national(first(record.get("NATIONAL")))
        owner = ""
        for column in _OWNER_COLUMNS:
            value = first(record.get(column))
            if value:
                owner = value
                break
        fate3 = first(record.get("FATE3"))
        captor_polity, captor_label = _FATE3.get(fate3, ("", ""))
        raw = {
            "FATE": fate_code,
            "FATE3": fate3,
            "NATIONAL": first(record.get("NATIONAL")),
            "YEARAM": first(record.get("YEARAM")),
            "SHIPNAME": ship_name,
            "RIG": rig,
            "OWNER": owner,
        }

        if is_loss:
            stage = fate_entry.get("stage", "")
            location_text, location_precision, uncertainty, imputed = _location(record, stage)
            label = fate_entry.get("label", "")
            cause = causes.classify(label)
            raw.update(
                {
                    "MJBYPTIMP": first(record.get("MJBYPTIMP")),
                    "PLAC1TRA": first(record.get("PLAC1TRA")),
                    "SLA1PORT": first(record.get("SLA1PORT")),
                    "MJSLPTIMP": first(record.get("MJSLPTIMP")),
                }
            )
            loss_rows.append(
                {
                    "source": meta["source"],
                    "source_record_id": record_id,
                    "source_url": meta["source_url"],
                    "tier": meta["tier"],
                    "licence": meta["licence"],
                    "redistribute": not imputed,
                    "ship_name": ship_name,
                    "ship_type": rig,
                    "loss_date": parsed.iso if parsed else None,
                    "loss_year": parsed.year if parsed else None,
                    "date_precision": parsed.precision if parsed else "none",
                    "location_text": location_text or None,
                    "location_precision": location_precision,
                    "uncertainty_km": uncertainty,
                    "geocode_method": "none",
                    "origin_raw": national_label or None,
                    "origin_polity": national_polity or None,
                    "origin_basis": "registered" if national_polity else None,
                    "flag_at_loss_raw": national_label or None,
                    "flag_at_loss_polity": national_polity or None,
                    "owner_at_loss": owner or None,
                    "cause_raw": label or None,
                    "cause_class": cause.cause_class,
                    "weather_related": cause.weather_related,
                    "is_total_loss": cause.is_total_loss,
                    "raw": raw,
                }
            )
        else:
            if not captor_polity and fate_entry:
                captor_polity = fate_entry.get("captor_polity", "")
            label = fate_entry.get("label", "") if fate_entry else ""
            mechanism = "condemned" if "condemned" in label.casefold() else "captured"
            event_rows.append(
                {
                    "source": meta["source"],
                    "source_record_id": record_id,
                    "ship_name": ship_name,
                    "date": parsed.iso if parsed else None,
                    "date_precision": parsed.precision if parsed else "none",
                    "from_polity": national_polity or None,
                    "to_polity": captor_polity or None,
                    "mechanism": mechanism,
                    "captor": captor_label or None,
                    "raw": raw,
                }
            )

    losses = losses_frame(loss_rows) if loss_rows else empty_losses()
    events = (
        pd.DataFrame([event_row(**row) for row in event_rows]) if event_rows else empty_events()
    )
    return Extract(losses=losses, events=events)
