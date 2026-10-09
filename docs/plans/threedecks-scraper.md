# Three Decks ship scraper: implementation and test plan

Status: draft, 2026-10-02; scope extended 2026-10-08. The site owner approved a full crawl of the ship catalogue at the robots.txt rate of one request every 5 s. At that rate the crawl takes about 2.5 days, so it must survive being cancelled or crashing (section 4.3). On 2026-10-08 he extended the scope to actions (battle pages) and fleet lists. Each has its own crawler and plan: [threedecks-actions.md](threedecks-actions.md) and [threedecks-fleets.md](threedecks-fleets.md).

## 1. Purpose and scope

[Age of Sail GIS datasets.md](../../Age%20of%20Sail%20GIS%20datasets.md) names Three Decks (threedecks.org) as the richest single source for the Spanish-losses timelapse. It stores captures, wrecks, burnings and renamings as dated events, and it keeps one record per ownership period. A Spanish ship taken into British service is therefore two linked records. The research doc's plan wants Three Decks to fill the years before 1796 and to add captor names.

The scraper collects **ships and ship metadata**: one record per Three Decks ship ID, holding the base facts, dimensions, armament, complement, commanders, service-history events and cited sources. It also collects the site's **captures index**, a ready list of "ship X taken by ship Y".

Out of scope: officer, place and class pages, which are kept only as linked IDs; geocoding; and deriving the loss-event table. Those are downstream steps that consume this scraper's output. The Three Decks ship ID is Wikidata property P11085, so the output joins directly to Wikidata.

Battle (action) pages and fleet lists have been in scope since 2026-10-08. They're crawled by two separate crawlers, each with its own plan: [threedecks-actions.md](threedecks-actions.md) and [threedecks-fleets.md](threedecks-fleets.md). This ship scraper never fetches them.

## 2. Permission and conduct

### 2.1 Permission record

- **Granted by:** Cy Harrison, owner of Three Decks. Reported 2026-10-02. Keep the reply email on file outside git.
- **Scope:** the full ship catalogue (about 31,000 ship pages), plus the Captures list and the ship search pages used to seed it. This goes beyond the original request in Appendix A.
- **Extension (reported 2026-10-08):** the Actions index and action pages (`show_battle`), and the Fleet Lists index and fleet-list pages. The request is Appendix B. Place pages are not included. Keep this reply on file outside git as well.
- **Condition:** a slow rate. This is implemented as the robots.txt `Crawl-delay` of 5 s between requests, one request at a time. It applies to the extension too.

### 2.2 Site context that still applies

- Every page still carries "Copyright © Cy Harrison 2010-2026, all rights reserved". Permission to extract data for this project is not permission to republish the pages.
- `robots.txt` (last modified 2025-08-26) allows `index.php` pages and sets `Crawl-delay: 5`. It disallows `/ajax/`, `/datafiles/`, `/php/`, `/scripts/` and `/utilities/`. It blocks GPTBot, ChatGPT-User, Google-Extended and CCBot entirely.
- The site sits behind Cloudflare.

### 2.3 Rules for this project

Rules 1 to 4 are the owner's condition and the promises made in the request; treat them as binding.

1. **Slow rate (the owner's condition).** Leave at least 5 s between requests, make one request at a time, and obey robots.txt.
2. **Be identifiable.** Use one honest User-Agent with a project URL and a contact address read from the `THREEDECKS_CONTACT` environment variable. Never hard-code a personal email.
3. **Attribute, don't republish.** Every derived dataset or map credits Three Decks and keeps the source codes that each value cites. Raw pages are never republished.
4. **No AI-training use** of the scraped pages or data.
5. **No evasion.** This overrides the generic Scrapy advice on rotating User-Agents and proxies: there is no UA rotation, no proxies and no Cloudflare-challenge solving. Permission does not change this. A 429 or a Cloudflare challenge pauses the crawl (15, 30, then 60 min, or `Retry-After`) and retries the same request unchanged. A 403, a Cloudflare block page, a fourth block in a row or four blocks inside 2 h close the spider `blocked` (`middlewares.py`); then stop and contact the owner rather than work around it.
6. **Fetch each page once.** The persistent HTTP cache is the source of truth. Re-parsing and resuming never re-fetch.
7. **Stay on ship, action and fleet-list data.** Fetch only ship pages, the Captures list, ship search results, the action index and action (battle) pages, and the fleet-list index and fleet-list pages. Officer, place, class, shipyard and source pages are out of scope; keep only their IDs. (Amended 2026-10-08, when battle pages and fleet lists came into scope.)
8. **Nothing scraped goes into git.** The repo has a GitHub remote, so treat it as public. Keep `data/` and `tests/fixtures/real/` in `.gitignore`. Every record carries provenance.
9. **If permission is narrowed or withdrawn,** stop at once, then delete the HTTP cache and any scraped data outside the new scope.
10. **One crawler at a time.** Scrapy's `DOWNLOAD_DELAY` applies per process, so two crawls running together would send two requests every 5 s and break rule 1. `scripts/crawl.py` (and so `crawl_all.py`) and `scripts/smoke.py` hold an OS lock on `data/threedecks/crawl.lock` (`threedecks/lock.py`), and a second one refuses to start. `scripts/fetch_fixtures.py` joins them in task S1 of [threedecks-actions.md](threedecks-actions.md) / [threedecks-fleets.md](threedecks-fleets.md). The spiders themselves take no lock, so never run `scrapy crawl` by hand against the real site. (Added 2026-10-08.)

## 3. Recon findings (2026-10-02)

Pages examined: robots.txt, `siteindex.xml`, `ships.xml`, data definitions, ships 2682, 2744 and 6358, the captures form plus one query, and the ship search form.

### 3.1 Site mechanics

- Plain server-rendered PHP. Every value is in the HTML, so no browser rendering is needed and Playwright/Splash are unnecessary. The DataTables script only paginates a table that is already complete in the HTML.
- **Smoke run, 2026-10-03 (103 requests, all 200):** pages come zstd-compressed (20 to 72 KB decoded), so anything that reads the HTTP cache outside Scrapy must decode it (`threedecks.cache.load_cached_response`). Cloudflare injects `/cdn-cgi/challenge-platform/scripts/jsd/main.js` into every ordinary page, so that string is not a challenge marker. Every ship page ends with `span#copywrite_message` ("Copyright © Cy Harrison 2010-2026, all rights reserved"), which the completeness check requires. Some pages carry a "Fleets" table whose body rows have no `<tr>`.
- Ship URL: `https://threedecks.org/index.php?display_type=show_ship&id={id}`. Responses take about 1.0 to 2.0 s and weigh 35 to 65 KB. With zlib they compress to 7 to 13 KB.
- **Sitemap:** `ships.xml` lists 25,300 unique ship IDs (min 1, max 28,756) and has no lastmod per URL. The index's lastmod is 2019-01-24, while the homepage claims about 30,984 ships, so the sitemap is stale and incomplete.
- **Captures index:** POST `index.php?display_type=select_capture` with `select_from_nation`, `select_by_nation`, `select_war` and `select_captures=Change Filter`.
  - Spain (7) → Great Britain (1) returns **361 rows** dated 1704 to 1830, in one 281 KB response that takes about 8 s.
  - Columns: date, captured ship (`a.shiplink`), and captor ship(s) followed by `. Place text`.
  - 22 rows have no captor ship link, only free text such as "Taken by the British".
- **Ship search:** POST `index.php?display_type=ships_search` with `show_shiplist=1`, `page`, `limit` (default 50), `select_nation` (Spain=7, Great Britain=1, France=4) and `sel_origin` (3=Captured, 9=Captured on the Stocks), plus name, rate, type, yard and date filters.
  - **Results markup (examined 2026-10-02):** `table#shiplists`, one `tr.shiplistdetailrow` per ship, ship id in the Name cell's first `a.shiplink`. A renamed vessel links both names, so the first link is the row's id. The header text is "Ship Search Results, N Records Found Showing Page X of Y". The `limit` is honoured (50 rows per page; 38 pages for 1,863 Spanish records).
  - A missing ship id returns the "Find a ship" search page (`<title>Find a ship</title>`, no `table#ship_base`). This is the not-found signature used for the completeness check and the Tier C upward-scan stop rule.
  - The captures list has 361 data rows; 22 rows have no captor link (one of them has no captured-ship link either, only free text).

### 3.2 Ship page structure (verified with parsel on 2682)

| Field | Where | Notes |
|---|---|---|
| Name | `h1.LaunchName::text` | |
| ID | `table#ship_base th.showid::text` | |
| Base facts | `table#ship_base tbody tr`: label `td[1]`, value `td[2]`, source code `td.source_col a::text` | Labels vary per ship: Nominal Guns, Nationality, Operator, Ordered, Keel Laid Down, Named, Launched, How acquired, Shipyard, Ship Class, Designed by, Constructor, Category, Ship Type, Sailing Rig, Captured, Sold, Previously, Becomes, … |
| Nation | `a[href*="show_nation"]` in the value cell | The name varies by era ("Great Britain" vs "United Kingdom of Great Britain and Ireland"). **Key on the ID.** |
| Incarnation links | rows labelled `Previously` / `Becomes` → `a.shiplink` | 2744 `Becomes` → 6358; 6358 `Previously` → 2744 |
| Class, yard, people, type | `a.shipclasslink`, `a[href*="show_shipyard"]`, `a[href*="show_crewman"]`, `a[href*="ship_type"]` | The Shipyard cell has **nested `<a>`** (yard and region); take all of them. |
| Sections | `div` blocks headed by `h2` | Headings carry counts ("15 Ship Commanders", "1 Commissioned Officer"). Match with `^\d+\s+` stripped. Sections are optional: 6358 has no Armament. |
| Dimensions, armament, complement, officers, history | `span` grids, with rows separated by `<br>` | One group per source code. Dimensions appear up to 3 times (B006, AGMAB, SWoA on 2682). |
| Service history | the `div` whose h2 is "Service History" | **Do not select by id.** It reuses `id="ship_complement"`. Rows hold a date span (with a `@title` tooltip), the event span (which can link to `show_battle` or `show_ship`) and an optional source span. |
| Sources | `div#source_list > div` | code `a[name]`, title `a[href*="show_source"]`, authors `a[href*="show_author"]`, type in the last span |
| Notes | `div#table_page_notes` | |

Markup hazards:

- Armament rows put `<td>`/`<th>` inside `<span>`. lxml keeps the text, which was verified.
- Sidebars ("Recent updates", "Recent comments") and the comment table are full of `a.shiplink`. **Never follow links generically.** Follow only the explicit fields (`Previously`, `Becomes`, captures rows, search results), and scope extraction to `div#datacol`.
- Row grouping: in span grids, split a section's child nodes on `<br>` into rows. Do not pair `span.column1` with its next sibling, because the date and the source code both use `span.column1`.

### 3.3 Dates

- Ship pages use `D.M.YYYY` with partial forms such as `4.1788` and `1790`. Julian dates between 1 January and 25 March carry two years, as in `1.2.1702/03`. The tooltip `@title` holds the text form plus a Gregorian equivalent: "1st February 1702 (NS 12th February 1703)".
- The captures list uses `YYYY/MM/DD`, `YYYY/MM` and `YYYY`, plus a `bef.` prefix.
- Both formats can carry `bef.`, `aft.` or `c.` (circa): `c.18.6.1744`, `aft.15.2.1745/46`. The qualifier is kept in `TDDate.qualifier`.
- The captures list can name the same ship and date twice, once per captor (Diligencia, 1804/12/07), so capture rows are keyed by their captors too.

### 3.4 Data quality signals (keep raw; do not reconcile in the scraper)

- The capture date disagrees between incarnations: 2744 says Captured 22.10.1805, while 6358 and the captures list say 21.10.1805.
- The captures list is incomplete. San José (112), taken at Cape St Vincent in 1797, does not appear under "San José" or "San Josef", though San Nicolás from the same action does. Treat the list as a seed, not as ground truth.
- At least one row is anomalous: Nuestra Señora del Rosario (active 1587 to 1588) is dated 1704/04/16.

## 4. Architecture

```
pyproject.toml                     # uv; deps: scrapy (behaviour below verified on 2.19.0), parsel; dev: pytest, pytest-cov, ruff
scrapers/threedecks/
  scrapy.cfg
  threedecks/
    settings.py
    items.py                       # dataclass items (Scrapy supports them natively)
    pages.py                       # PageKind registry: one entry per entity page type
    forms.py                       # form payloads shared by spiders and fetch_fixtures
    kinds_actions.py               # registers the 'action' PageKind
    kinds_fleets.py                # registers the 'fleet' PageKind
    state.py                       # StateStore: frontier, per-page status and records in SQLite (4.3)
    cache.py                       # SqliteCacheStorage: crash-safe HTTP cache (4.3)
    parsing/                       # PURE functions: (html|Selector, url) -> dataclasses. No Scrapy imports.
      dates.py                     # TDDate parser for both formats + tooltip
      common.py                    # shared visible-text/link/footer helpers
      grid.py                      # span_rows(section) -> list[list[node]]; section_by_heading()
      ship_page.py                 # parse_ship(selector, url) -> ShipRecord
      actions.py                   # parse_action_index / parse_action -> action items
      fleets.py                    # parse_fleet_index / parse_fleet -> fleet items
      captures.py                  # parse_captures(selector, query) -> list[CaptureRow]
      search.py                    # parse_search(selector) -> (ship_ids, has_next)
    spiders/
      base.py                      # TDSpider: kind-agnostic entity callback, incarnation following, seeding
      captures.py                  # Tier A
      ships_by_nation.py           # Tier B (optional)
      ships_all.py                 # Tier C: every ship ID
      actions.py                   # the actions crawler (index + action pages)
      fleets.py                    # the fleets crawler (fleet-list index + fleet pages)
    pipelines.py                   # Validation -> StatePipeline (upsert record + mark page done, one transaction)
    middlewares.py                 # BlockDetectionMiddleware
scripts/
  fetch_fixtures.py                # polite fetch of the fixture list into tests/fixtures/real/
  crawl_status.py                  # done / pending / not found / errors, pages per hour, ETA (ships, actions, fleets)
  reparse.py                       # re-run the parsers over the cache, offline
  export.py                        # state.sqlite -> ships/actions/fleets JSONL, captures JSONL, Parquet
  qa_report.py                     # post-crawl data quality report (ships, actions and fleets)
tests/
  fixtures/synthetic/              # hand-written minimal HTML reproducing each quirk (committed)
  fixtures/real/                   # gitignored; populated by fetch_fixtures.py
data/threedecks/                   # gitignored: httpcache.sqlite, state.sqlite, exports/
```

Design choices:

- **Parsing is separate from crawling.** Spiders only build requests and call `parsing.*`. All extraction logic is testable offline, and a parser fix can be replayed over the whole HTTP cache without touching the site.
- **Plain functions over ItemLoader.** The pages are label/value tables and `<br>`-delimited span grids, so `section_by_heading` + `span_rows` helpers are clearer than loader processors.
- **Lossless capture.** Every base row is kept as `{label, text, links, date, source_code}`, even when the label is unknown. Typed convenience fields are derived from those rows. Labels not on a known list are counted in stats (`threedecks/unknown_label/<label>`), so new fate labels (Wrecked, Burnt, Foundered, …) surface instead of vanishing.
- **Progress lives on disk, not in Scrapy's memory.** See 4.3.
- **Configurable base URL.** The `THREEDECKS_BASE_URL` setting (default `https://threedecks.org`) drives start URLs and `allowed_domains`, so the resume tests can point the spiders at a local server.

### 4.1 Items

```python
@dataclass
class TDDate:
    raw: str                      # "1.2.1702/03", "bef.1799/03", "4.1788"
    iso: str | None               # "1702-02-01" | "1788-04" | "1790"
    precision: str | None         # "day" | "month" | "year"
    qualifier: str | None         # "bef." ...
    julian_alt_year: int | None   # 1703 for "1.2.1702/03"
    tooltip: str | None           # "1st February 1702 (NS 12th February 1703)"
    gregorian_iso: str | None     # from the NS part, when present

@dataclass
class ShipRecord:
    td_id: int
    name: str
    base_rows: list[BaseRow]               # lossless
    nation_id: int | None; nation_name: str | None; operator: str | None
    nominal_guns: str | None               # raw ("74", "Unknown")
    category: str | None; ship_type: str | None; ship_type_id: int | None; rig: str | None
    how_acquired: str | None
    class_id: int | None; class_name: str | None
    shipyards: list[LinkRef]; designers: list[LinkRef]; constructors: list[LinkRef]
    previous_td_ids: list[int]; next_td_ids: list[int]
    lifecycle: list[LabeledDate]           # every base row whose value is a date (Launched, Captured, Sold...)
    dimensions: list[DimensionSet]; armament: list[ArmamentSet]; complement: list[ComplementRow]
    officers: list[OfficerRow]             # section heading, from/to, rank, crewman_id, name, source
    fleets: list[FleetRow]                 # dates, fleet_id/name, commander_id/name, source
    history: list[HistoryEvent]            # date, text, battle_ids, ship_ids, source_code
    sources: list[SourceRef]; notes: str | None
    unknown_labels: list[str]; unknown_sections: list[str]
    url: str; fetched_at: str; content_sha256: str; parser_version: str

@dataclass
class CaptureRow:
    captured_td_id: int; captured_label: str; date: TDDate
    captor_td_ids: list[int]; captor_text: str; place_text: str | None
    from_nation_id: int; by_nation_id: int; war_id: int
```

Items are **not** written through Scrapy feeds. Feeds append, so a resumed run would duplicate records, and a hard kill can truncate the last line. Instead, `StatePipeline` upserts each item into `state.sqlite`. Ships are keyed by `td_id`; capture rows are keyed by (from, by, war, captured_td_id, raw date). `scripts/export.py` writes `ships.jsonl`, `captures.jsonl` and Parquet from there.

### 4.3 Resuming after a cancel or crash

**Goal:** after any interruption, rerunning the same command continues where the crawl stopped. Interruptions include Ctrl+C, a closed terminal, a crash, a reboot and a power cut. No page is fetched twice, except at most the one in flight at a hard kill, and no record is written twice.

**Two built-in Scrapy options don't meet this goal:**

- **JOBDIR** saves the request queue only on a clean shutdown (a single Ctrl+C). A second Ctrl+C, a crash, a closed terminal or a power cut can lose or corrupt it. It also doesn't record which pages were parsed successfully.
- **The default file cache** is not crash-safe. Verified in 2.19.0: `FilesystemCacheStorage.store_response` writes the metadata file before the body. A kill mid-write leaves an entry that looks cached but has a missing or truncated body. Scrapy treats a missing body as a miss, but it serves a truncated one as if it were complete.

**Design:**

1. **State in SQLite.** The state lives in `data/threedecks/state.sqlite`, in WAL mode, with one transaction per page. It has these tables:
   - `frontier(td_id PK, discovered_by, depth, status, attempts, http_status, last_error, updated_at)`, where status is `pending | done | not_found | error | parse_error`.
   - `ships(td_id PK, record_json, parser_version, content_sha256, fetched_at)` and `captures(key PK, row_json)`.
   - `runs(run_id, spider, started_at, finished_at, close_reason, pages_fetched)`, which the status script reads.
2. **Record work before requesting it.** Every seed is inserted with `INSERT OR IGNORE` before its request is scheduled. Seeds are sitemap IDs, gap-fill IDs, captures and search results, and `Previously`/`Becomes` links. Discovered work therefore survives a crash.
3. **Mark done together with the record.** `StatePipeline` upserts the record and sets its frontier row to `done` in one transaction. A page is never `done` without its record.
4. **Start from the database.** On start, each spider seeds its frontier (this is idempotent). It then schedules only the rows not yet `done` or `not_found`, in ascending `td_id`. `start_requests` streams them lazily, so 31k IDs don't sit in memory.
5. **Crash-safe cache.** `SqliteCacheStorage` implements Scrapy's four-method cache storage interface in about 50 lines. It stores each response in one transaction, zlib-compressed and keyed by request fingerprint. Suppose the crawler dies after a fetch but before the record commits: the restart replays that page from the cache. Scrapy returns cache hits before the downloader's delay slot (verified in 2.19.0), so replays are instant and send nothing to the site.
6. **Completeness check.** A ship page counts only if it contains `table#ship_base` and the footer copyright line, or if it matches the not-found signature (to be found in Phase 1). Otherwise its cache entry is deleted and the page is marked `error`, so it is refetched on the next run.
7. **Errors don't stop the crawl.**
   - A network failure that outlasts the retries marks the page `error` and increments `attempts`. Restarts retry it, up to 3 attempts in total; after that it waits for manual review.
   - A parser exception marks the page `parse_error`, and the crawl moves on. Fix the parser, then run `scripts/reparse.py`, which works offline from the cache.
   - A 429 or a challenge page pauses the crawl for a cool-off and retries. A plain 403, or a block that outlasts the cool-offs, closes the spider with reason `blocked` and leaves the state intact. Investigate, then resume.
8. **Shutdown.** One Ctrl+C, or Ctrl+Break on Windows, finishes the in-flight request and commits; Scrapy handles SIGINT, SIGTERM and SIGBREAK. A second Ctrl+C or a kill loses at most the one in-flight page. The restart refetches it, or replays it from the cache.

**Operating a run:**

```
just threedecks-crawl-1000               # 1,000 more ships (~1.5 h); rerun for the next 1,000
just threedecks-crawl 5000               # or: run the tiers until 5,000 ships are stored
uv run python scripts/crawl_status.py    # done / pending / not found / errors, pages per hour, ETA
uv run python scripts/export.py          # write JSONL + Parquet from state.sqlite
```

`scripts/crawl.py` runs tiers A, B and C in order and skips a tier whose last run finished. It keeps Windows awake while it runs (the screen stays on), logs to `data/threedecks/logs/`, restarts a tier that makes no progress for 20 minutes outside a Cloudflare cool-off, and retries a tier that lost the network after 5, 10 and 20 minutes without charging the pages' attempts. It warns at start when Windows has an update waiting to restart the PC: an update reboot still stops the crawl (2026-10-03: standby at 23:22 on idle timeout, then an update reboot at 04:17), so pause updates for long sessions.

To start over, delete `state.sqlite`; delete `httpcache.sqlite` too if pages must be refetched. There is deliberately no reset flag, so a typo can't wipe two days of progress.

## 5. Crawl strategy

Throughput is about 7.7 s per page (a 5-7 s delay, 6 s on average, plus about 1.7 s response): roughly 450 pages per hour, or 11,000 per day.

| Tier | Seeds | Follows | Size / time |
|---|---|---|---|
| Smoke | captures ES→GB | none, cap 25 | 25 pages, ~3 min |
| A | captures ES→GB (1 POST) | captured and captor ships, then `Previously`/`Becomes` to depth 1 | ~590 ship IDs + incarnations ≈ 900 pages, ~1.7 h |
| B (optional) | search `select_nation=7` (all Spanish ships), plus search `select_nation=1&sel_origin=3` (British ships acquired by capture) | incarnations to depth 2 | count read from the search header in Phase 1 |
| C | every ship ID: the 25,300 in `ships.xml`, then every other ID up to the highest known one (the sitemap's 28,756, or higher if an earlier tier found one: Tier A finds IDs above 34,000), then upward until 200 consecutive not-found responses | none (every ID is seeded) | ~31,000 to 33,000 pages, ~2.5 days |

All tiers share the state database and the cache, so a page fetched by one tier is skipped by the next. Run A first, because it delivers the Spanish-losses core in under 2 hours. B is worth running only if the Spanish records are needed before C finishes, since C fetches them anyway. C also covers captures missing from the captures list (such as San José), because the British record's `Previously` link exists either way. The upward scan's stop rule depends on the not-found signature (Phase 1). The homepage figure of about 30,984 ships implies IDs above the sitemap's maximum.

## 6. Test plan

Every layer except 7 and 8 runs offline in CI.

1. **Unit tests: `parsing/dates.py`** (parametrised). Cases: `22.1.1785`, `4.1788`, `1790`, `1.2.1702/03` (Julian alternate year, plus the NS tooltip → `gregorian_iso` 1703-02-12), `1704/04/16`, `1718/02`, `bef.1799`, `bef.1799/03`, `?`, empty and malformed input (raw is kept and other fields are None). Also dimension and gun-string helpers: `190' 0"` → 190.0 ft, `1,815.5` → 1815.5, `28 Spanish 24-Pounder` → (28, Spanish, 24, Pounder), `4 Spanish 32-Pound Obús`. Raw strings are always kept.
2. **Parser tests on synthetic fixtures** (committed, written by hand). Each one reproduces a quirk from 3.2–3.4: duplicate `id="ship_complement"`, td inside span, nested Shipyard anchors, count-prefixed headings, missing Armament, `Previously`/`Becomes`, a history row with a battle link plus a ship link plus a source code, a sidebar full of shiplinks (none may leak into items), an unknown base label (it lands in `unknown_labels`), a captures row without a captor link, and a `bef.` date.
3. **Golden tests on real pages** (`@pytest.mark.real_pages`, skipped if `tests/fixtures/real/` is absent). Assertions sit in test code; the HTML is gitignored.
   - 2682: 16 base rows, nation_id 7, Launched `1785-01-22`, Captured `1805-10-21`, class_id 739, shipyard IDs [284, 1947], 3 dimension sets (B006, AGMAB, SWoA), 3 armament sets (1785, 1799, 1805), 83 history events, battle 157 on 21.10.1805, 7 sources, 15 commanders.
   - 2744: `next_td_ids == [6358]`, Captured `1805-10-22`.
   - 6358: `previous_td_ids == [2744]`, nation_id 1, no armament, Sold `1816-01-08`.
   - Captures ES→GB: 361 rows, 22 without a captor ID.
   - Every fixture: `unknown_sections == []`.
4. **Spider tests** (offline, `HtmlResponse` built from fixtures):
   - The captures spider issues one `FormRequest` with the right formdata. `parse` yields `CaptureRow`s and one ship request per unique ID.
   - Incarnation following respects depth and never follows sidebar links.
   - Search pagination stops on an empty page.
   - Seeding is idempotent: running `start_requests` twice inserts each ID once and schedules only rows that are still pending.
   - The block middleware closes the spider on a plain 403, waits out a 429 or a challenge (doubling, honouring `Retry-After`) and closes after the last cool-off.
5. **Resume tests** (offline). A local HTTP server serves fixture pages, and a test settings profile points `THREEDECKS_BASE_URL` at it and sets the delay to 0.
   - `StateStore` unit tests: idempotent seeding, done-plus-record in one transaction, attempt counting, and reopening the file keeps everything.
   - `SqliteCacheStorage`: store/retrieve round trip; POST bodies keyed separately; an exception mid-store leaves no entry.
   - **Graceful stop:** run the spider in a subprocess over 200 fake IDs. After 50 items, send Ctrl+Break (SIGINT on POSIX), then rerun to completion. Assert that every ID is `done` exactly once, the server saw each ID once, and the export has 200 unique records.
   - **Hard kill:** the same, but with `proc.kill()` after 50 items. The same assertions hold, except that the server may see at most one ID twice.
   - **Truncated cache entry:** plant a truncated body for one ID. The rerun detects it, refetches it, and the record comes out complete.
   - **Blocked:** the server returns 429 at ID 30, and the spider closes with `blocked`. Once the server recovers, a rerun completes the crawl.
7. **Live smoke and resume check** (manual; the only tests that touch the network).
   - Run `just threedecks-smoke` (`scripts/smoke.py`: the captures spider, closed after 25 responses). It passes if items validate, no `blocked` close occurs, no page fails to fetch, parse or pass the completeness check, and the unknown-section stats are zero. Unknown labels are listed but do not fail it. The pages go into the normal cache, so a rerun replays them without touching the site.
   - Then start Tier A, press Ctrl+C after about 10 pages and rerun. The rerun must skip or cache-hit those pages and continue from the next one.
8. **Post-crawl QA** (`scripts/qa_report.py`), run after each tier:
   - counts per nation, and the share of records with a Launched date
   - unknown labels by frequency (feed these back into the known list)
   - incarnation symmetry (A→B implies B→A)
   - captures rows whose captured ship lacks a capture-type lifecycle row, and the reverse
   - capture-date mismatches between linked incarnations (report only)
   - records with `unknown_sections`, and frontier rows stuck in `error` or `parse_error`

CI (GitHub Actions) runs `ruff check` and `pytest -m "not real_pages"`.

## 7. Phases and exit criteria

| Phase | Work | Exit criteria |
|---|---|---|
| 0 | Add `data/` and `tests/fixtures/real/` to `.gitignore`. | `.gitignore` updated. |
| 1 | `uv init`; add deps; `scrapy startproject`. Write `fetch_fixtures.py` and fetch: 2682, 2744, 6358; captures ES→GB; search results pages 1 and 2 for Spain; one ID missing from the sitemap (to learn the not-found signature); one ship with alternate names; one pre-1752 British ship with Julian dates; one wrecked and one burnt ship; one ship with 3 or more incarnations. Write the synthetic fixtures. | Fixtures on disk. Open questions in section 8 marked answered. |
| 2 | TDD the parsers: dates → grid helpers → captures → ship page → search. | Layers 1–3 green. |
| 3 | Spiders, `StateStore`, `SqliteCacheStorage`, pipelines, middlewares, settings, and the status, reparse and export scripts. | Layers 4–5 green; layer 7 passes. |
| 4 | Tier A. | About 900 records; QA report reviewed; parser fixes replayed with `reparse.py`. |
| 5 | Tier C, in as many sessions as convenient (Tier B first, if Spanish records are needed early). | Every frontier row is `done`, `not_found`, or `error` after 3 attempts; error list reviewed; QA report. |
| 6 | Export and hand off to the loss-event build. | JSONL and Parquet written; QA report attached. |

## 8. Open questions and risks

- **Scope:** permission covers the full ship catalogue, action pages and fleet lists (since 2026-10-08), all at 5 s per request. If permission is narrowed or withdrawn, follow rule 9 in section 2.3.
- **Long run:** about 2.5 days of continuous crawling. Interruptions are handled by the resume design (4.3), and `crawl_status.py` gives an ETA.
- **Disk:** the cache will hold about 31,000 to 33,000 pages at 7 to 13 KB compressed, roughly 300 to 400 MB.
- **Unverified mechanics** to settle in Phase 1:
  - the not-found response for a missing ID (needed for the completeness check and the upward scan's stop rule)
  - the search results markup and its total-count header
  - whether `limit` above 50 is honoured (a larger page cuts the number of requests)
  - where alternate names appear in the markup
  - **Answered 2026-10-02 (Phase 1 fixtures):** a missing ID returns the "Find a ship" page; search results are `table#shiplists` with a `tr.shiplistdetailrow` per ship and a "N Records Found / Page X of Y" header; `limit=50` gives 50 rows per page; renamed vessels link both names in the Name cell, and the first link is the row's id. See section 3.1.
- **Cloudflare** may start challenging automated clients.
- **Markup drift:** the golden tests, the unknown-label and unknown-section stats, and the replay-from-cache workflow catch it cheaply.
- **Source disagreement** (3.4) is preserved as raw data and resolved downstream, with the Three Decks source codes kept per value.
## Appendix A: original permission request

This is the original request. The owner later extended the scope to the full ship catalogue, on condition of a slow rate (reported 2026-10-02). Section 2.1 records the current terms. The promises below (identification, attribution, no republishing, no AI training) still apply, as rules 2 to 4.

> Subject: Request to extract Spanish ship records from Three Decks for a research map
>
> Dear Cy Harrison,
>
> I'm building a non-commercial historical map of Spanish naval losses to Britain in the Age of Sail. Three Decks is by far the best record of these events, and I'd like to ask your permission before collecting any of it automatically.
>
> What I'd like to do: read the ship pages for Spanish-flagged ships and their British captors (roughly 1,000 pages to start, possibly all Spanish ships later), plus your Captures list. The crawler would make one request every 5 seconds or slower, obey robots.txt, identify itself with a contact address, and fetch each page only once.
>
> How the data would be used: the dates, places and captors would be geocoded for the map, with attribution to Three Decks and to the sources each value cites. I wouldn't republish your pages, and none of it would be used for AI training.
>
> Would this be acceptable? If you'd prefer a different scope or rate, or if you could share an export instead, I'd be very happy to work that way.
>
> With thanks,
> [name, contact]

## Appendix B: scope-extension request (sent; granted 2026-10-08)

The owner granted actions and fleet lists with no further conditions. Place pages, the optional paragraph, were not granted.

> Subject: Three Decks: request to extend the ship crawl to actions and fleet lists
>
> Dear Cy Harrison,
>
> Thank you again for permitting the ship-catalogue crawl. It runs exactly as agreed: one request every 5 seconds, one at a time, identified by its User-Agent, and each page fetched only once.
>
> I'd like to ask whether you'd allow the same crawler to read two more parts of the site: the Actions list and its action pages (`show_battle`), and the Fleet Lists and their pages. For the map of Spanish naval losses, the action pages give the place and the opposing forces behind each loss, which the ship pages alone don't. I'll confirm the page counts before starting, and the rate and conditions would stay the same.
>
> [Optional: If the action pages locate actions by place, I'd also like to ask about the place pages, for their coordinates only.]
>
> The earlier promises stand: attribution to Three Decks and to the sources each value cites, no republishing of your pages, and no use for AI training. If you'd prefer a narrower scope, a slower rate, or an export, I'll gladly work that way.
>
> With thanks,
> [name, contact]
