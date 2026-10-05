"""CLI entry point for the ship-losses analysis (plan section 4).

Usage: ``uv run --extra analysis python analyses/01-ship-losses/build.py --stage all``.
"""

from __future__ import annotations

import argparse
import os
import sys
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from shiplosses import dedupe, geocode, ownership, qa
from shiplosses.mapping import interactive, static
from shiplosses.paths import DATA, DATA_RAW, OUTPUTS
from shiplosses.registry import ID_TO_SOURCE, SOURCES
from shiplosses.schema import empty_events, empty_losses, validate_events, validate_losses

STAGES = ["extract", "geocode", "ownership", "dedupe", "map", "all"]


def _utcnow() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _write_frame(frame: pd.DataFrame, base: Path) -> None:
    base.parent.mkdir(parents=True, exist_ok=True)
    frame.to_parquet(base.with_suffix(".parquet"), index=False)
    frame.to_csv(base.with_suffix(".csv"), index=False)


def extract_sources(modules, raw_root: Path) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    loss_frames, event_frames, counts = [], [], {}
    for module in modules:
        result = module.extract(raw_root)
        loss_frames.append(result.losses)
        event_frames.append(result.events)
        counts[module.ID] = len(result.losses)
    losses = pd.concat(loss_frames, ignore_index=True) if loss_frames else empty_losses()
    events = pd.concat(event_frames, ignore_index=True) if event_frames else empty_events()
    return losses, events, counts


def _load(path: Path, fallback: pd.DataFrame) -> pd.DataFrame:
    return pd.read_parquet(path) if path.exists() else fallback


def run(args: argparse.Namespace) -> int:
    stages = set(STAGES[:-1]) if args.stage == "all" else {args.stage}
    OUTPUTS.mkdir(parents=True, exist_ok=True)
    losses_path = OUTPUTS / "losses_all.parquet"
    events_path = OUTPUTS / "ownership_events.parquet"

    if args.source:
        unknown = [s for s in args.source if s not in ID_TO_SOURCE]
        if unknown:
            print(f"unknown source ids: {unknown}", file=sys.stderr)
            return 2
    modules = [ID_TO_SOURCE[source] for source in args.source] if args.source else SOURCES

    if "extract" in stages:
        losses, events, counts = extract_sources(modules, DATA_RAW)
        losses = losses.sort_values("loss_id", kind="stable").reset_index(drop=True)
        events = events.sort_values("event_id", kind="stable").reset_index(drop=True)
        problems = validate_losses(losses) + validate_events(events)
        if problems:
            print("schema problems:", *problems, sep="\n  ", file=sys.stderr)
        for source_name, subset in losses.groupby("source", sort=True):
            _write_frame(subset, OUTPUTS / "per-source" / str(source_name))
        _write_frame(losses, OUTPUTS / "losses_all")
        _write_frame(events, OUTPUTS / "ownership_events")
        print("extracted:", ", ".join(f"{k}={v}" for k, v in counts.items()))
    else:
        losses = _load(losses_path, empty_losses())
        events = _load(events_path, empty_events())

    unresolved: dict[str, int] = {}
    if "geocode" in stages:
        gaz = geocode.Gazetteers(DATA, DATA_RAW)
        losses = geocode.geocode_losses(losses, gaz, unresolved=unresolved)
        if args.online_geocode:
            contact = os.environ.get("DR_CONTACT")
            if contact:
                losses = geocode.geocode_online(
                    losses, OUTPUTS / "geocode_cache.csv", contact
                )
            else:
                print("note: --online-geocode needs DR_CONTACT; skipped")
        print(f"geocoded; {len(unresolved)} unresolved place phrases")

    if "ownership" in stages:
        losses = ownership.resolve(losses, events)

    if "dedupe" in stages:
        losses = dedupe.dedupe(losses)

    if {"extract", "geocode", "ownership", "dedupe"} & stages:
        losses = losses.sort_values("loss_id", kind="stable").reset_index(drop=True)
        _write_frame(losses, OUTPUTS / "losses_all")

    if "map" in stages:
        build_date = _utcnow()
        if args.redistributable_only:
            shared = losses[losses["redistribute"] == True]  # noqa: E712
            interactive.build(shared, OUTPUTS / "map_shareable.html", build_date=build_date)
        interactive.build(losses, OUTPUTS / "map.html", build_date=build_date)
        static.build(losses, OUTPUTS, DATA_RAW)
        qa.write_reports(losses, events, OUTPUTS, unresolved, build_date=build_date)
        print("wrote map.html and qa_report.md")

    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the ship-losses analysis.")
    parser.add_argument("--source", action="append", default=[], help="source id (repeatable)")
    parser.add_argument("--stage", choices=STAGES, default="all")
    parser.add_argument("--online-geocode", action="store_true")
    parser.add_argument("--redistributable-only", action="store_true")
    return run(parser.parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
