"""Link ownership events to losses (plan section 6.1)."""

from __future__ import annotations

import pandas as pd
from rapidfuzz import fuzz, process

from .normalize import dates

MIN_NAME_SCORE = 90
MAX_GAP_YEARS = 30


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _year(value: object) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def resolve(losses: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    if losses.empty or events.empty:
        return losses
    event_rows = []
    for event in events.to_dict("records"):
        parsed = dates.parse_date(event.get("date"))
        event["_year"] = parsed.year if parsed else None
        event_rows.append(event)

    by_name: dict[str, list[dict]] = {}
    for event in event_rows:
        key = _str(event.get("ship_name_norm"))
        if key:
            by_name.setdefault(key, []).append(event)
    by_prefix: dict[str, list[str]] = {}
    for key in by_name:
        by_prefix.setdefault(key[:2], []).append(key)

    for index, row in losses.iterrows():
        if row.get("owner_at_loss"):
            continue
        key = _str(row.get("ship_name_norm"))
        if not key:
            continue
        flag = row.get("flag_at_loss_polity")
        origin = row.get("origin_polity")
        if not flag and not origin:
            continue
        loss_year = _year(row.get("loss_year"))
        if loss_year is None:
            continue

        candidates = by_name.get(key)
        if candidates is None:
            pool = by_prefix.get(key[:2]) or list(by_name)
            match = process.extractOne(
                key, pool, scorer=fuzz.token_sort_ratio, score_cutoff=MIN_NAME_SCORE
            )
            if not match:
                continue
            candidates = by_name[match[0]]

        best = None
        best_score = 0.0
        for event in candidates:
            score = fuzz.token_sort_ratio(_str(event.get("ship_name_norm")), key)
            if score < MIN_NAME_SCORE:
                continue
            event_year = event.get("_year")
            if event_year is not None:
                gap = loss_year - event_year
                if gap < 0 or gap > MAX_GAP_YEARS:
                    continue
            polity_match = (flag and event.get("to_polity") == flag) or (
                origin and event.get("from_polity") == origin
            )
            if not polity_match:
                continue
            if score > best_score:
                best, best_score = event, score
        if best is None:
            continue
        losses.at[index, "owner_at_loss"] = best.get("to_polity") or best.get("captor")
        losses.at[index, "ownership_changed"] = True
        date_text = best.get("date") or "date unknown"
        change = f"{best.get('mechanism', 'changed hands')} to {best.get('to_polity')}"
        losses.at[index, "ownership_change"] = f"{change}, {date_text} ({best.get('source')})"
        losses.at[index, "ownership_event_ids"] = [best.get("event_id")]
    return losses
