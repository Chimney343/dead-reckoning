"""Command-line interface: ``python -m fetch ...``."""

from __future__ import annotations

import argparse
import sys

from . import core, manifest, run, validate


def _group_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--group",
        action="append",
        choices=sorted(manifest.VALID_GROUPS),
        help="restrict to a group (repeatable)",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="fetch", description="Download the Age of Sail datasets.")
    sub = parser.add_subparsers(dest="command", required=True)

    list_cmd = sub.add_parser("list", help="list sources")
    _group_args(list_cmd)

    get_cmd = sub.add_parser("get", help="download sources")
    _group_args(get_cmd)
    get_cmd.add_argument("--id", dest="ids", action="append", help="source id (repeatable)")
    get_cmd.add_argument("--large", action="store_true", help="include large sources")
    get_cmd.add_argument("--force", action="store_true", help="re-download existing files")
    get_cmd.add_argument(
        "--dry-run", action="store_true", help="resolve and print, download nothing"
    )

    extract_cmd = sub.add_parser("extract", help="unpack archives for one source")
    extract_cmd.add_argument("id")

    sub.add_parser("validate", help="write data/raw/_inventory.csv and README.md")

    manual_cmd = sub.add_parser("manual", help="show manual/blocked sources")
    manual_cmd.add_argument(
        "--mark", action="store_true", help="write provenance for present files"
    )

    return parser


def _fmt_size(n: int) -> str:
    if not n:
        return "?"
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f}{unit}" if unit == "B" else f"{n/1:.1f}{unit}"
        n /= 1024
    return f"{n}"


def cmd_list(entries, args) -> int:
    groups = set(args.group) if args.group else None
    selected = manifest.select(entries, groups=groups, include_large=True)
    print(f"{'id':32} {'group':9} {'status':8} {'size':>8}  licence")
    for entry in selected:
        print(
            f"{entry.id:32} {entry.group:9} {entry.status:8} "
            f"{_fmt_size(entry.approx_bytes):>8}  {entry.licence[:40]}"
        )
    return 0


def cmd_get(entries, args) -> int:
    contact = core.resolve_contact()
    groups = set(args.group) if args.group else None
    ids = set(args.ids) if args.ids else None
    with core.HttpClient(contact=contact) as client:
        run.fetch_entries(
            entries,
            client,
            groups=groups,
            ids=ids,
            include_large=args.large,
            force=args.force,
            dry_run=args.dry_run,
        )
    return 0


def cmd_extract(entries, args) -> int:
    entry = manifest.get_entry(entries, args.id)
    extracted = run.extract_entry(entry)
    if not extracted:
        print(f"no archives found for {args.id}")
        return 1
    for path in extracted:
        print(f"extracted {path.name}")
    return 0


def cmd_validate(entries, args) -> int:
    inventory, readme = validate.run(entries)
    print(f"wrote {inventory}")
    print(f"wrote {readme}")
    return 0


def cmd_manual(entries, args) -> int:
    report = run.manual_report(entries)
    if not report:
        print("no manual sources")
        return 0
    for item in report:
        mark = "present" if item["present"] else "missing"
        print(f"[{mark}] {item['id']}: {item['title']}")
        print(f"         save to: {item['dest']}")
        print(f"         source:  {item['url']}")
        if item["notes"]:
            print(f"         note:    {item['notes']}")
    if args.mark:
        for item in report:
            if item["present"]:
                manifest_entry = manifest.get_entry(entries, item["id"])
                run.mark_manual(manifest_entry)
                print(f"marked {item['id']} as manual")
    return 0


COMMANDS = {
    "list": cmd_list,
    "get": cmd_get,
    "extract": cmd_extract,
    "validate": cmd_validate,
    "manual": cmd_manual,
}


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    entries = manifest.load_manifest()
    try:
        return COMMANDS[args.command](entries, args)
    except (KeyError, core.DownloadError, core.MissingContactError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
