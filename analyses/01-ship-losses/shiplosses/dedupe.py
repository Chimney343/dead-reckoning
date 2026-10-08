"""De-duplication: deterministic links then fuzzy clusters (plan section 6.2)."""

from __future__ import annotations

import json
import math
import re

import pandas as pd
from rapidfuzz import fuzz

PRECISION_RANK = {"surveyed": 0, "reported": 1, "place": 2, "region": 3, "none": 4, None: 4}
SOURCE_RANK = [
    "ireland-infomar",
    "emodnet-shipwrecks",
    "ireland-wiid",
    "wa-shipwrecks",
    "ukho-wrecks",
    "wikipedia",
    "slavevoyages",
    "prize-papers",
    "zenodo-shipwrecks",
    "novascotia-shipwrecks",
    "dutch-asiatic-shipping",
    "todo-a-babor",
    "ibm-maritime-archives",
]
TARGET_FIELDS = [
    "lat",
    "lon",
    "location_text",
    "location_precision",
    "uncertainty_km",
    "geocode_method",
    "origin_polity",
    "owner_at_loss",
    "cause_class",
    "loss_date",
    "loss_year",
    "date_precision",
]
WIID_KEY = re.compile(r"^W\d+$", re.IGNORECASE)
BUCKET_CAP = 400


class _UnionFind:
    def __init__(self, size: int) -> None:
        self.parent = list(range(size))

    def find(self, item: int) -> int:
        while self.parent[item] != item:
            self.parent[item] = self.parent[self.parent[item]]
            item = self.parent[item]
        return item

    def union(self, a: int, b: int) -> None:
        root_a, root_b = self.find(a), self.find(b)
        if root_a != root_b:
            self.parent[root_b] = root_a


def _str(value: object) -> str:
    return value if isinstance(value, str) else ""


def _raw(row: pd.Series) -> dict:
    value = row.get("raw")
    if isinstance(value, dict):
        return value
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _deterministic_key(row: pd.Series) -> str | None:
    source = row.get("source")
    record = str(row.get("source_record_id") or "")
    if source in {"ireland-wiid", "ireland-infomar", "emodnet-shipwrecks"}:
        raw = _raw(row)
        field = {
            "ireland-wiid": "Wreck No",
            "ireland-infomar": "nms_ref",
            "emodnet-shipwrecks": "source_id",
        }[source]
        key = raw.get(field) or record
        return f"wiid:{key}" if WIID_KEY.match(str(key)) else None
    if source == "ibm-maritime-archives":
        wreck_id = str(_raw(row).get("wreck_id") or "")
        return f"das:{wreck_id.split(':', 1)[1]}" if wreck_id.startswith("maarer:") else None
    if source == "dutch-asiatic-shipping":
        return f"das:{record}" if record else None
    if source in {"zenodo-shipwrecks", "wikipedia"}:
        name = row.get("ship_name_norm")
        year = row.get("loss_year")
        flag = row.get("flag_at_loss_polity")
        return f"zname:{name}|{year}|{flag}"
    return None


def _distance_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * radius * math.asin(min(1.0, math.sqrt(a)))


def _fuzzy_link(
    names: list[str],
    sources: list[str],
    years: list,
    lats: list,
    lons: list,
    texts: list[str],
    uf: _UnionFind,
) -> None:
    buckets: dict[tuple[str, int], list[int]] = {}
    for index, name in enumerate(names):
        year = years[index]
        if not name or pd.isna(year):
            continue
        buckets.setdefault((name[:2], int(year)), []).append(index)
    for (prefix, year), members in buckets.items():
        if len(members) > BUCKET_CAP:
            continue
        neighbours = members + buckets.get((prefix, year + 1), [])
        for position, i in enumerate(neighbours):
            for j in neighbours[position + 1 :]:
                if sources[i] == sources[j]:
                    continue
                if uf.find(i) == uf.find(j):
                    continue
                if abs(int(years[i]) - int(years[j])) > 1:
                    continue
                if fuzz.token_sort_ratio(names[i], names[j]) < 90:
                    continue
                if pd.notna(lats[i]) and pd.notna(lats[j]):
                    if _distance_km(lats[i], lons[i], lats[j], lons[j]) > 50:
                        continue
                else:
                    tokens_i = set(texts[i].casefold().split())
                    tokens_j = set(texts[j].casefold().split())
                    union = tokens_i | tokens_j
                    overlap = len(tokens_i & tokens_j) / len(union) if union else 0.0
                    if overlap < 0.5:
                        continue
                uf.union(i, j)


def dedupe(losses: pd.DataFrame) -> pd.DataFrame:
    if losses.empty:
        return losses
    losses = losses.reset_index(drop=True)
    size = len(losses)
    uf = _UnionFind(size)

    keys: dict[str, list[int]] = {}
    for index, row in losses.iterrows():
        key = _deterministic_key(row)
        if key:
            keys.setdefault(key, []).append(int(index))
    for members in keys.values():
        for other in members[1:]:
            uf.union(members[0], other)

    names = [_str(value) for value in losses["ship_name_norm"]]
    sources = [_str(value) for value in losses["source"]]
    years = pd.to_numeric(losses["loss_year"], errors="coerce").tolist()
    lats = pd.to_numeric(losses["lat"], errors="coerce").tolist()
    lons = pd.to_numeric(losses["lon"], errors="coerce").tolist()
    texts = [_str(value) for value in losses["location_text"]]
    _fuzzy_link(names, sources, years, lats, lons, texts, uf)

    counts = losses[TARGET_FIELDS].notna().sum(axis=1).tolist()
    precision = [
        PRECISION_RANK.get(value, 4) for value in losses["location_precision"].tolist()
    ]
    source_rank = [
        SOURCE_RANK.index(source) if source in SOURCE_RANK else len(SOURCE_RANK)
        for source in sources
    ]

    def primary_key(position: int) -> tuple:
        return (precision[position], source_rank[position], -counts[position])

    clusters: dict[int, list[int]] = {}
    for position in range(size):
        clusters.setdefault(uf.find(position), []).append(position)

    for number, (_, members) in enumerate(sorted(clusters.items()), start=1):
        identifier = f"c{number}"
        for member in members:
            losses.loc[member, "cluster_id"] = identifier
            losses.loc[member, "is_primary"] = False
        if len(members) == 1:
            losses.loc[members[0], "is_primary"] = True
            continue
        ordered = sorted(members, key=primary_key)
        primary = ordered[0]
        losses.loc[primary, "is_primary"] = True
        for field in TARGET_FIELDS:
            if losses.loc[primary, field] is not None:
                continue
            for donor in ordered[1:]:
                value = losses.loc[donor, field]
                if value is not None:
                    losses.loc[primary, field] = value
                    from_column = f"{field}_from"
                    if from_column in losses.columns:
                        losses.loc[primary, from_column] = losses.loc[donor, "loss_id"]
                    break
    return losses
