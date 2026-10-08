"""Generate the committed SlaveVoyages code tables from the codebook PDF.

Run once with ``uv run python analyses/01-ship-losses/scripts/sv_codebook.py``;
the emitted ``data/sv/{fate,nation,places}.csv`` are reviewed and committed.
"""

from __future__ import annotations

import csv
import re
from pathlib import Path

from pypdf import PdfReader

REPO_ROOT = Path(__file__).resolve().parents[3]
RAW_PDF = REPO_ROOT / "data" / "raw" / "slavevoyages" / "SPSS_Codebook_2023-11-06.pdf"
OUT_DIR = Path(__file__).resolve().parents[1] / "data" / "sv"

LOSS_CODES = {2, 3, 4, 5, 39, 66, 75, 96, 99}
CAPTURE_CODES = (
    set(range(6, 32))
    | {42, 43, 45, 46, 47, 48}
    | {50, 51, 52, 53, 56, 74}
)

STAGES = {
    2: "before_embarkation",
    3: "after_embarkation",
    4: "after_disembarkation",
    5: "",
    39: "",
    66: "",
    75: "after_embarkation",
    96: "before_embarkation",
    99: "after_embarkation",
}

NATION_POLITY = {
    "U.S.A.": "United States",
    "Hanse Towns, Brandenburg": "Hanse Towns",
    "Denmark / Baltic": "Denmark",
    "Duchy of Courland": "Courland",
    "Other": "",
}

_CAPTOR_PATTERNS = (
    (re.compile(r"british", re.IGNORECASE), "Great Britain"),
    (re.compile(r"\bspanish\b", re.IGNORECASE), "Spain"),
    (re.compile(r"dutch", re.IGNORECASE), "Netherlands"),
    (re.compile(r"portuguese", re.IGNORECASE), "Portugal"),
    (re.compile(r"french", re.IGNORECASE), "France"),
    (re.compile(r"united states|\bus\b", re.IGNORECASE), "United States"),
    (re.compile(r"brazil", re.IGNORECASE), "Brazil"),
    (re.compile(r"swed", re.IGNORECASE), "Sweden"),
    (re.compile(r"dan", re.IGNORECASE), "Denmark"),
)

_FATE_ENTRY = re.compile(r"^(\d{1,3})\s+(\S.*)$")
_NATION_ENTRY = re.compile(r"^(\d{1,3})\s+(\S.*)$")
_PLACE_ENTRY = re.compile(r"(\d{5})\s+(.*?)(?=\s+\d{5}\b|$)")


def read_lines(pdf_path: Path) -> list[str]:
    """Return the PDF's text split into lines."""
    reader = PdfReader(str(pdf_path))
    lines: list[str] = []
    for page in reader.pages:
        lines.extend((page.extract_text() or "").splitlines())
    return lines


def parse_fate_entries(lines: list[str]) -> dict[int, str]:
    """Parse the ``FATE`` (outcome of voyage) value table."""
    start = None
    for index, line in enumerate(lines):
        if "Particular outcome of voyage" in line:
            start = index
            break
    if start is None:
        return {}
    entries: dict[int, str] = {}
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("FATE2"):
            break
        if not stripped or stripped.startswith("FATE") or stripped == "Value Label":
            continue
        match = _FATE_ENTRY.match(stripped)
        if match:
            code = int(match[1])
            entries.setdefault(code, match[2].strip())
    return entries


def parse_nation_entries(lines: list[str]) -> dict[int, str]:
    """Parse the ``NATIONAL`` (country of registration) value table."""
    start = None
    for index, line in enumerate(lines):
        if "Country in which ship registered" in line:
            start = index
            break
    if start is None:
        return {}
    entries: dict[int, str] = {}
    for line in lines[start:]:
        stripped = line.strip()
        if stripped.startswith("TONNAGE"):
            break
        if not stripped or stripped in {"NATIONAL", "Value Label"}:
            continue
        match = _NATION_ENTRY.match(stripped)
        if match:
            code = int(match[1])
            entries.setdefault(code, match[2].strip())
    return entries


def parse_place_entries(lines: list[str]) -> dict[str, str]:
    """Parse the place-code listing into ``code -> label``."""
    start = None
    for index, line in enumerate(lines):
        if line.strip() == "Broad Regions":
            start = index
            break
    if start is None:
        return {}
    entries: dict[str, str] = {}
    for line in lines[start:]:
        for match in _PLACE_ENTRY.finditer(line):
            code = match[1]
            label = match[2].strip().strip(",")
            if code.isdigit() and label:
                entries.setdefault(code, label)
    return entries


def captor_from_label(label: str) -> str:
    """Infer the captor polity named in a ``FATE`` label."""
    for pattern, polity in _CAPTOR_PATTERNS:
        if pattern.search(label):
            return polity
    return ""


def build_fate_rows(entries: dict[int, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code in sorted(entries):
        label = entries[code]
        is_loss = code in LOSS_CODES
        is_capture = code in CAPTURE_CODES
        captor = captor_from_label(label) if (is_capture or is_loss) else ""
        rows.append(
            {
                "code": code,
                "label": label,
                "is_loss": "true" if is_loss else "false",
                "is_capture": "true" if is_capture else "false",
                "captor_polity": captor,
                "stage": STAGES.get(code, ""),
            }
        )
    return rows


def build_nation_rows(entries: dict[int, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code in sorted(entries):
        label = entries[code]
        polity = NATION_POLITY.get(label, label)
        rows.append({"code": code, "label": label, "polity": polity})
    return rows


def build_place_rows(entries: dict[str, str]) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for code in sorted(entries):
        rows.append(
            {
                "code": code,
                "label": entries[code],
                "is_region": "true" if code.endswith("99") else "false",
            }
        )
    return rows


def write_csv(path: Path, columns: list[str], rows: list[dict[str, object]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    lines = read_lines(RAW_PDF)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_csv(
        OUT_DIR / "fate.csv",
        ["code", "label", "is_loss", "is_capture", "captor_polity", "stage"],
        build_fate_rows(parse_fate_entries(lines)),
    )
    write_csv(
        OUT_DIR / "nation.csv",
        ["code", "label", "polity"],
        build_nation_rows(parse_nation_entries(lines)),
    )
    write_csv(
        OUT_DIR / "places.csv",
        ["code", "label", "is_region"],
        build_place_rows(parse_place_entries(lines)),
    )


if __name__ == "__main__":
    main()
