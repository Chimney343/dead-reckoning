"""Open every downloaded file, count rows/features, and write an inventory.

Also generates ``data/raw/README.md`` from the manifest so the data directory
documents its own sources, licences and fetch dates.
"""

from __future__ import annotations

import csv
import json
import zipfile
from pathlib import Path

from . import core, manifest

DELIMITED = {".csv": ",", ".tsv": "\t", ".tab": "\t"}
INVENTORY_FIELDS = [
    "source_id",
    "group",
    "dest",
    "subdir",
    "file",
    "kind",
    "rows",
    "features",
    "columns",
    "crs",
    "bytes",
    "sha256",
    "licence",
    "tier",
    "redistribute",
    "fetched_at",
]


def _count_delimited(path: Path, delimiter: str) -> tuple[int, str]:
    with open(path, encoding="utf-8", errors="replace", newline="") as fh:
        reader = csv.reader(fh, delimiter=delimiter)
        try:
            header = next(reader)
        except StopIteration:
            return 0, ""
        count = sum(1 for _ in reader)
    return count, ";".join(header)


def _inspect_gpkg(path: Path) -> dict:
    try:
        import pyogrio
    except ImportError:
        return {"features": None, "crs": "", "note": "install the validate extra"}
    info = pyogrio.read_info(path)
    crs = info.get("crs")
    return {"features": int(info.get("features", 0)), "crs": str(crs) if crs else ""}


def _inspect_sav(path: Path) -> dict:
    try:
        import pyreadstat
    except ImportError:
        return {"rows": None, "columns": "", "note": "install the validate extra"}
    _, meta = pyreadstat.read_sav(str(path), metadataonly=True)
    return {"rows": meta.number_rows, "columns": ";".join(meta.column_names)}


def inspect_file(path: Path) -> dict:
    path = Path(path)
    suffix = path.suffix.lower()
    info: dict = {
        "file": path.name,
        "kind": suffix.lstrip(".") or "other",
        "rows": None,
        "features": None,
        "columns": "",
        "crs": "",
        "bytes": path.stat().st_size,
    }
    try:
        if suffix in DELIMITED:
            rows, columns = _count_delimited(path, DELIMITED[suffix])
            info.update(rows=rows, columns=columns)
        elif suffix == ".txt":
            info["kind"] = "txt"
            info["rows"] = sum(1 for _ in open(path, "rb"))
        elif suffix in {".geojson", ".json"}:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("type") == "FeatureCollection":
                info.update(kind="geojson", features=len(data.get("features", [])))
            elif isinstance(data, dict):
                info.update(kind="json", columns=";".join(list(data)[:20]))
            elif isinstance(data, list):
                info.update(kind="json", rows=len(data))
        elif suffix == ".zip":
            with zipfile.ZipFile(path) as zf:
                info["rows"] = len(zf.namelist())
        elif suffix == ".rar":
            try:
                import rarfile

                with rarfile.RarFile(path) as rf:
                    info["rows"] = len(rf.namelist())
            except ImportError:
                info["note"] = "install the rar extra"
        elif suffix in {".gpkg", ".shp"}:
            info.update(_inspect_gpkg(path))
        elif suffix == ".sav":
            info.update(_inspect_sav(path))
    except (OSError, ValueError, zipfile.BadZipFile) as exc:  # pragma: no cover - defensive
        info["note"] = str(exc)
    return info


def build_inventory(entries: list[manifest.Entry], root: Path | None = None) -> list[dict]:
    root = root or manifest.data_root()
    rows: list[dict] = []
    for entry in entries:
        dest = manifest.entry_dir(entry, root)
        if not dest.exists():
            continue
        provenance = core.read_provenance(dest / "_provenance.json")
        file_prov = provenance.get("files", {})
        for path in sorted(dest.rglob("*")):
            if not path.is_file() or path.name == "_provenance.json":
                continue
            if path.name.startswith(".") or path.suffix == ".part":
                continue
            info = inspect_file(path)
            rel = path.relative_to(dest).as_posix()
            prov = file_prov.get(rel, {})
            rows.append(
                {
                    "source_id": entry.id,
                    "group": entry.group,
                    "dest": entry.dest,
                    "subdir": entry.subdir,
                    "file": rel,
                    "kind": info["kind"],
                    "rows": info["rows"],
                    "features": info["features"],
                    "columns": info["columns"],
                    "crs": info["crs"],
                    "bytes": info["bytes"],
                    "sha256": core.sha256_file(path),
                    "licence": provenance.get("licence", entry.licence),
                    "tier": provenance.get("tier", entry.tier),
                    "redistribute": provenance.get("redistribute", entry.redistribute),
                    "fetched_at": prov.get("fetched_at", provenance.get("fetched_at", "")),
                }
            )
    return rows


def write_inventory(
    entries: list[manifest.Entry],
    root: Path | None = None,
    out: Path | None = None,
) -> Path:
    root = root or manifest.data_root()
    out = out or (root / "_inventory.csv")
    rows = build_inventory(entries, root)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=INVENTORY_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return out


def write_readme(
    entries: list[manifest.Entry],
    root: Path | None = None,
    out: Path | None = None,
) -> Path:
    root = root or manifest.data_root()
    out = out or (root / "README.md")
    lines = [
        "# Raw sources",
        "",
        "Generated from `fetch/manifest.yaml` by `python -m fetch validate`.",
        "Files are not committed; this list records where they came from.",
        "",
        "| id | title | group | status | tier | licence | red. | files | fetched |",
        "|----|-------|-------|--------|------|---------|------|-------|---------|",
    ]
    for entry in entries:
        dest = manifest.entry_dir(entry, root)
        provenance = core.read_provenance(dest / "_provenance.json")
        files = provenance.get("files", {})
        fetched = provenance.get("fetched_at", "")
        if not files and entry.status == "manual" and dest.exists():
            present = [p for p in dest.rglob("*") if p.is_file() and p.name != "_provenance.json"]
            files = {p.name: {} for p in present}
            fetched = "(manual)"
        template = (
            "| {id} | {title} | {group} | {status} | {tier} | {licence} "
            "| {red} | {n} | {fetched} |"
        )
        lines.append(
            template.format(
                id=entry.id,
                title=entry.title.replace("|", "/"),
                group=entry.group,
                status=entry.status,
                tier=entry.tier,
                licence=entry.licence.replace("|", "/"),
                red="yes" if entry.redistribute else "no",
                n=len(files),
                fetched=fetched or "-",
            )
        )
    lines.append("")
    lines.append("Notes:")
    for entry in entries:
        if entry.notes:
            lines.append(f"- **{entry.id}**: {entry.notes}")
    lines.append("")
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def run(entries: list[manifest.Entry] | None = None, root: Path | None = None) -> tuple[Path, Path]:
    entries = entries if entries is not None else manifest.load_manifest()
    inventory = write_inventory(entries, root)
    readme = write_readme(entries, root)
    return inventory, readme
