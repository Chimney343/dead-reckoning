"""Orchestrate fetching, archive extraction and the manual-source workflow."""

from __future__ import annotations

import zipfile
from pathlib import Path
from urllib.parse import urlparse

from . import core, harvesters, manifest, resolvers


def _write_provenance(dest_dir: Path, entry, resolver_input: dict, files: dict) -> dict:
    record = dict(entry.source_meta)
    record["resolver_input"] = resolver_input
    record["files"] = files
    record["fetched_at"] = core.utcnow()
    core.write_provenance(dest_dir / "_provenance.json", record)
    return record


def fetch_entry(
    entry: manifest.Entry,
    client: core.HttpClient,
    root: Path | None = None,
    *,
    force: bool = False,
    dry_run: bool = False,
) -> dict:
    if entry.status in {"manual", "skip"}:
        return {"id": entry.id, "status": entry.status, "files": {}}

    dest_dir = manifest.entry_dir(entry, root)
    prior_files = core.read_provenance(dest_dir / "_provenance.json").get("files", {})

    if entry.rate_limit:
        for url in entry.urls:
            host = urlparse(url).hostname
            if host:
                client.limiter.per_host[host] = entry.rate_limit

    if entry.resolver in harvesters.HARVESTERS:
        harvest = harvesters.HARVESTERS[entry.resolver]
        result = harvest(
            entry,
            client,
            dest_dir,
            prior_files=prior_files,
            force=force,
            dry_run=dry_run,
        )
        files = result.get("files", {})
        resolver_input = result.get("resolver_input", {})
    else:
        specs = resolvers.resolve(entry, client)
        if dry_run:
            return {
                "id": entry.id,
                "status": "dry-run",
                "specs": [{"filename": s.filename, "urls": s.urls} for s in specs],
            }
        files = {}
        resolver_input = {}
        for spec in specs:
            prior = prior_files.get(spec.filename, {})
            result = core.download_file(client, spec, dest_dir, prior=prior, force=force)
            files[spec.filename] = {**result.as_provenance(), "skipped": result.skipped}
            resolver_input.update(spec.meta)

    if not dry_run:
        _write_provenance(dest_dir, entry, resolver_input, files)
    return {"id": entry.id, "status": entry.status, "files": files}


def plan_lines(entries: list[manifest.Entry], contact: str | None) -> list[str]:
    """Describe the sources a run will download, one line each.

    Harvesters that need a contact are flagged so the operator can set one
    before the run hits a refusal.
    """
    if not entries:
        return ["nothing to download"]
    lines = [f"{len(entries)} source(s) to download:"]
    needing: list[str] = []
    for entry in entries:
        contact_needed = harvesters.requires_contact(entry.resolver)
        flag = "  [needs DR_CONTACT]" if contact_needed else ""
        lines.append(f"  {entry.id:32} {entry.group:9} {entry.status:8}{flag}")
        if contact_needed:
            needing.append(entry.id)
    if needing and not contact:
        lines.append(
            "note: no contact set (DR_CONTACT or THREEDECKS_CONTACT); "
            "will be refused: " + ", ".join(needing)
        )
    return lines


def fetch_entries(
    entries: list[manifest.Entry],
    client: core.HttpClient,
    root: Path | None = None,
    *,
    groups: set[str] | None = None,
    ids: set[str] | None = None,
    include_large: bool = False,
    force: bool = False,
    dry_run: bool = False,
    log=print,
) -> list[dict]:
    selected = manifest.select(entries, groups=groups, ids=ids, include_large=include_large)
    to_fetch = [e for e in selected if e.status not in {"manual", "skip"}]
    for line in plan_lines(to_fetch, client.contact):
        log(line)
    results = []
    for entry in selected:
        if entry.status in {"manual", "skip"}:
            log(f"skip   {entry.id} ({entry.status})")
            continue
        log(f"fetch  {entry.id} [{entry.group}/{entry.resolver}]")
        results.append(
            fetch_entry(entry, client, root, force=force, dry_run=dry_run)
        )
    return results


def _safe_extract_zip(archive: Path, out_dir: Path) -> None:
    out_dir = out_dir.resolve()
    with zipfile.ZipFile(archive) as zf:
        for member in zf.infolist():
            target = (out_dir / member.filename).resolve()
            if not str(target).startswith(str(out_dir)):
                raise RuntimeError(f"unsafe path in {archive.name}: {member.filename}")
        zf.extractall(out_dir)


def extract_entry(
    entry: manifest.Entry,
    root: Path | None = None,
    interim_root: Path | None = None,
) -> list[Path]:
    dest_dir = manifest.entry_dir(entry, root)
    out_dir = (interim_root or (manifest.repo_root() / "data" / "interim")) / entry.id
    extracted: list[Path] = []
    if not dest_dir.exists():
        return extracted
    for archive in sorted(dest_dir.rglob("*")):
        if not archive.is_file():
            continue
        name = archive.name.lower()
        if name.endswith(".zip"):
            _safe_extract_zip(archive, out_dir)
            extracted.append(archive)
        elif name.endswith(".rar"):
            try:
                import rarfile
            except ImportError as exc:  # pragma: no cover - depends on host
                raise RuntimeError(
                    "RAR extraction needs the 'rar' extra and 7-Zip or unrar on PATH"
                ) from exc
            out_dir.mkdir(parents=True, exist_ok=True)
            with rarfile.RarFile(archive) as rf:
                rf.extractall(out_dir)
            extracted.append(archive)
    return extracted


def manual_report(entries: list[manifest.Entry], root: Path | None = None) -> list[dict]:
    report = []
    for entry in entries:
        if entry.status != "manual":
            continue
        dest_dir = manifest.entry_dir(entry, root)
        present = False
        if dest_dir.exists():
            present = any(
                p.is_file() and p.name != "_provenance.json" for p in dest_dir.rglob("*")
            )
        report.append(
            {
                "id": entry.id,
                "title": entry.title,
                "dest": str(dest_dir),
                "url": entry.url,
                "notes": entry.notes,
                "present": present,
            }
        )
    return report


def mark_manual(entry: manifest.Entry, root: Path | None = None) -> dict:
    dest_dir = manifest.entry_dir(entry, root)
    if not dest_dir.exists():
        raise FileNotFoundError(f"{dest_dir} does not exist")
    files = {}
    for path in sorted(dest_dir.rglob("*")):
        if path.is_file() and path.name != "_provenance.json":
            files[path.relative_to(dest_dir).as_posix()] = {
                "bytes": path.stat().st_size,
                "sha256": core.sha256_file(path),
                "fetched_at": core.utcnow(),
            }
    record = {**entry.source_meta, "fetched_by": "manual", "files": files}
    core.write_provenance(dest_dir / "_provenance.json", record)
    return record
