# Age of Sail dataset downloads (python -m fetch), and the Three Decks crawler.
# See docs/plans/threedecks-scraper.md for the crawl tiers and the site owner's conditions.

set windows-shell := ["powershell.exe", "-NoLogo", "-NoProfile", "-Command"]
set dotenv-load := true

fetch := "uv run python -m fetch"

# List the recipes
default:
    @just --list

# Download every automatic source except the large ones; extra flags pass through (--force, --dry-run)
download *args:
    {{ fetch }} get {{ args }}

# Download every automatic source, large ones included (HGIS jurisdictions, STRO, Newberry, Lloyd's PDF, ...)
download-all *args:
    {{ fetch }} get --large {{ args }}

# Download one group: captures, wrecks, colonial, routes or trade
download-group group *args:
    {{ fetch }} get --group {{ group }} {{ args }}

# List the sources with their group, status, size and licence
sources:
    {{ fetch }} list

# Show the manual sources and whether their files are present
manual:
    {{ fetch }} manual

# Write data/raw/_inventory.csv and data/raw/README.md
validate:
    {{ fetch }} validate

# Live Three Decks smoke test: captures Spain->Britain, 25 pages at 5 s (~3 min); needs $env:THREEDECKS_CONTACT
threedecks-smoke *args:
    uv run python scripts/smoke.py {{ args }}

# Longer Three Decks smoke test: stop after 100 ship records (~12 min); needs $env:THREEDECKS_CONTACT
threedecks-smoke-100 *args:
    uv run python scripts/smoke.py --ships 100 {{ args }}

# Crawl Three Decks (tiers A, B, then C) until N ship records are stored; 5000 is ~11 h. Rerun to resume
threedecks-crawl ships="5000" *args:
    uv run python scripts/crawl.py --ships {{ ships }} {{ args }}

# Three Decks actions crawl (~2.3 h; separate from the ship tiers); rerun to resume, --rerun after Tier C
threedecks-actions *args:
    uv run python scripts/crawl.py --tiers actions {{ args }}

# Actions smoke test: parses battle 343 (The Spanish Armada; 2 sides, 349 ships) only (~30 s)
threedecks-actions-smoke *args:
    uv run python scripts/crawl.py --tiers actions -s THREEDECKS_ACTION_IDS=343 -s CLOSESPIDER_PAGECOUNT=25 {{ args }}

# Crawl 1,000 more ships than are stored now (~2 h), then stop; rerun for the next 1,000
threedecks-crawl-1000 *args:
    uv run python scripts/crawl.py --more 1000 {{ args }}

# Crawl 2,000 more ships than are stored now (~4 h), then stop; rerun for the next 2,000
threedecks-crawl-2000 *args:
    uv run python scripts/crawl.py --more 2000 {{ args }}

# The whole crawl (~3 days): 2,000-ship sessions until every tier finishes, then QA report and exports. Stops on a block, a run of broken pages or a parse-error spike; rerun to resume
threedecks-crawl-all *args:
    uv run python scripts/crawl_all.py {{ args }}

# Rebuild the ship-losses analysis (extract, geocode, ownership, dedupe, map); extra args pass through
ship-losses *args:
    uv run --extra analysis python analyses/01-ship-losses/build.py {{ args }}
