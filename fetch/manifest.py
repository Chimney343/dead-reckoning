"""Load and validate ``manifest.yaml``, the single source of truth for sources."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

VALID_GROUPS = {"captures", "wrecks", "colonial", "routes", "trade"}
VALID_STATUSES = {"verified", "listed", "resolve", "manual", "skip"}
FINAL_STATUSES = {"verified", "manual", "skip"}
REQUIRED_FIELDS = {"id", "group", "title", "resolver", "licence", "tier", "status"}


class ManifestError(ValueError):
    """The manifest is malformed."""


@dataclass
class Entry:
    id: str
    group: str
    title: str
    resolver: str
    licence: str
    tier: str
    status: str
    url: str = ""
    urls: list[str] = field(default_factory=list)
    filename: str | None = None
    dest: str = ""
    subdir: str = ""
    approx_bytes: int = 0
    large: bool = False
    redistribute: bool = True
    notes: str = ""
    rate_limit: float | None = None
    params: dict = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.dest:
            self.dest = self.id
        if not self.urls and self.url:
            self.urls = [self.url]

    @property
    def source_meta(self) -> dict:
        """The manifest fields carried into every provenance record."""
        return {
            "id": self.id,
            "group": self.group,
            "title": self.title,
            "resolver": self.resolver,
            "licence": self.licence,
            "tier": self.tier,
            "redistribute": self.redistribute,
            "status": self.status,
            "url": self.url,
            "dest": self.dest,
            "subdir": self.subdir,
            "notes": self.notes,
        }


def manifest_path() -> Path:
    return Path(__file__).with_name("manifest.yaml")


def repo_root() -> Path:
    return manifest_path().resolve().parent.parent


def data_root() -> Path:
    return repo_root() / "data" / "raw"


def entry_dir(entry: Entry, root: Path | None = None) -> Path:
    base = (root or data_root()) / entry.dest
    return base / entry.subdir if entry.subdir else base


def load_manifest(path: Path | str | None = None) -> list[Entry]:
    path = Path(path) if path else manifest_path()
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ManifestError(f"{path} must contain a YAML list of sources")
    entries: list[Entry] = []
    seen: set[str] = set()
    for item in raw:
        if not isinstance(item, dict):
            raise ManifestError(f"{path}: every source must be a mapping")
        missing = REQUIRED_FIELDS - item.keys()
        if missing:
            raise ManifestError(f"source {item.get('id', '?')} missing required: {sorted(missing)}")
        if item["group"] not in VALID_GROUPS:
            raise ManifestError(f"source {item['id']} has unknown group {item['group']!r}")
        if item["status"] not in VALID_STATUSES:
            raise ManifestError(f"source {item['id']} has unknown status {item['status']!r}")
        if item["id"] in seen:
            raise ManifestError(f"duplicate id {item['id']!r}")
        seen.add(item["id"])
        known = {f for f in Entry.__dataclass_fields__}
        kwargs = {k: v for k, v in item.items() if k in known}
        entries.append(Entry(**kwargs))
    return entries


def validate_statuses(entries: list[Entry]) -> None:
    unresolved = [e.id for e in entries if e.status not in FINAL_STATUSES]
    if unresolved:
        raise ManifestError(
            "every source must end verified, manual or skip; still open: "
            + ", ".join(unresolved)
        )


def get_entry(entries: list[Entry], entry_id: str) -> Entry:
    for entry in entries:
        if entry.id == entry_id:
            return entry
    raise KeyError(entry_id)


def select(
    entries: list[Entry],
    *,
    groups: set[str] | None = None,
    ids: set[str] | None = None,
    include_large: bool = False,
) -> list[Entry]:
    """Select sources to fetch.

    An explicit ``ids`` selection wins over ``groups`` and includes large
    sources, because naming a source is treated as intent.
    """
    if ids:
        return [e for e in entries if e.id in ids]
    result = list(entries)
    if groups:
        result = [e for e in result if e.group in groups]
    if not include_large:
        result = [e for e in result if not e.large]
    return result
