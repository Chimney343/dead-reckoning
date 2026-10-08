# Three Decks fleets: plan

Status: 2026-10-08. Permission granted. Recon done. Reconciled with the hardened scraper (commits e9ec193 and 2f63489; see 6.0). Ready to execute.

**For:** a coding agent.
- Sections 1–4 are the design.
- Sections 5–8 are the work: Part A (shared foundation) and Part B (the fleets crawler).
- Section 9 is the human operator's runbook.

The actions crawler has its own plan, [threedecks-actions.md](threedecks-actions.md). The two are built and scraped **independently**: either can be done first, and neither needs the other.

This plan extends [threedecks-scraper.md](threedecks-scraper.md) ("the ship plan"). Its rules (2.3), politeness settings (4.2), resume design (4.3) and test layers (6) all apply.

## 1. Scope

### 1.1 What the `fleets` crawler collects

- **The fleet-list index** (`index.php?display_type=show_fleetlist`): one page, 146 fleets.
- **Every fleet page** (`index.php?display_type=show_fleet&id={id}`). Each gives:
  - the fleet commander, and the formed and disbanded dates, each with its source
  - an optional introduction
  - every ship with its joined and left dates, its commander and notes
  - a dated event log that links ships, places and sometimes actions
  - cited sources

Fleet lists put ships in their squadron context and give dated positions for ships whose own history is thin. The output joins to ship records through `td_id`.

### 1.2 A separate crawler

- **Its own spider** (`fleets`), its own runs, its own frontier kinds (`fleet_index`, `fleet`), its own tables (`fleet_index`, `fleets`), its own exports and its own QA section.
- **It requests only two page types:** the fleet-list index (GET `show_fleetlist`) and fleet pages (GET `show_fleet`). It **never** requests ship, action (`show_battle`), action index, place, crewman or source pages. Fleet ships, commanders, places, and the actions linked from events are stored as IDs only. **It never follows event links to actions,** which belong to the actions crawler.
- **It has nothing to do with actions.** It doesn't import, read or write anything that belongs to the actions crawler.
- **What it shares with the ship crawler:** the settings, the HTTP cache file, the state file (separate tables), the base spider, and the `scripts/crawl.py` driver, which holds the crawl lock.
- **It never runs at the same time as any other crawl.** Rule 10 and the crawl lock enforce this. The lock lives in `scripts/crawl.py`, not in the spider, so live runs always go through `crawl.py` (section 9).

### 1.3 Out of scope

Ship, action, place, crewman and source pages (kept as IDs); geocoding; and anything about actions.

## 2. Permission and rules

The owner (Cy Harrison) granted actions and fleet lists on 2026-10-08, at the same 5 s rate, with no other conditions. The record is in ship plan 2.1, and the request text is in ship plan Appendix B. **Place pages are not permitted.**

Ship-plan rules 1–10 apply, notably:
- one request every 5 s, one at a time
- on a 429 or a challenge, pause and retry the same request unchanged; on a 403 or a Cloudflare block page, stop; never evade (`middlewares.py`)
- fetch each page once
- nothing scraped goes into git
- one crawler at a time

## 3. Recon findings (2026-10-08)

Fetched by `scripts/fetch_fixtures.py` at 5 s spacing into `tests/fixtures/real/` (gitignored):

- `fleetlist_index.html`
- `fleet_97.html` (Saumarez's Squadron 1798, British)
- `fleet_139.html` (Miguel Enriquez's privateer fleet, Spanish)
- `fleet_notfound_probe.html` (id 999999)

They weigh 17 to 96 KB.

### 3.1 Fleet-list index (`show_fleetlist`)

- **One GET page, no pagination:** 146 fleets, with unique IDs from 1 to 151.
- **Markup quirk.** The `tbody` of the first `table.column9` in `#datacol` holds **730 `td` cells directly, with no `tr` rows**. lxml keeps them flat, so group them in fives, in document order:
  1. **Date From** and 2. **Date To:** `span[@title]` in `D.M.YYYY`, `M.YYYY` or `YYYY` form.
  3. **Nationality:** a `show_nation` link, or the text "Unknown?".
  4. **Fleet:** an `a[href*=show_fleet]`.
  5. **Fleet Commander:** a `show_crewman` link in a `div.tooltip`, or `&nbsp;`.
- **First row:** 2.1501 / 1501 / Unknown? / fleet 132, "French Fleet sent to the aid of the Venetians" / no commander.
- **Nations:** Great Britain 37, Royaume de France 31, Kingdom of England 27, Unknown? 9, … Only 3 fleets are Spanish (`nation_id` 7): privateer fleets 146, 151 and 139, from 1658 to 1704.

### 3.2 Fleet page (`show_fleet&id=N`)

- `<title>` and `h1` both hold the fleet name. The ID appears only in the URL and in the comment form's hidden `id`.
- **An optional `h2` "Introduction"** is followed by `p` text (fleet 139).
- **The content is three `table.column8` elements with no id.** Recognise them by shape, never by position:
  1. **Base table.** Label/value rows: "Fleet Commander" (a `show_crewman` link), "Fleet Formed" and "Fleet Disbanded" (a date `span[@title]` in `td.column1`). Each row ends with `td.source_col a` (`#ref:1239`).
  2. **Ships table.** The header `th` cells are Ship / Joined / Left / Commander / Notes, but the data rows have **7 `td` cells**, not 5, because of empty spacer cells. Pick cells by class and content:
     - the shiplink in the first `td.column2`
     - the two `td.column1` date cells (Joined, Left)
     - the commander in the `td.column2` holding a `show_crewman` link (else `&nbsp;`)
     - the notes in the last `td.column2`
  3. **Events table.** The header cells are Date / Event / Source.
     - The date is a `span.date_field` in `YYYY/MM/DD` form (tooltip "Tuesday 14th of August 1798"), or plain text such as `c.1704`.
     - `td.col_info_text` holds the event text, which may link ships, places (`show_shipyard`) and actions (`show_battle`).
     - `td.source_col` holds the source.
- **Tooltips.** Every `div.tooltip` carries a `span.tooltiptext` (ship years and rate, or crewman nationality and service). It **must be excluded** from visible labels, names and notes, and kept in `LinkRef.tooltip`, as ship parser v4 does (`common.links`).
- **Other sections.** `div#source_list` uses the ship markup. The comments block ("Recent comments to other pages", `table#comment_list_table`, which contains `show_ship` links) is ignored.
- **Golden numbers:**

  | Fleet | Commander | Formed / disbanded | Ships | Events | Sources | Other |
  |---|---|---|---|---|---|---|
  | 97, Saumarez's Squadron 1798 | [4757] | 1798-08-14 / 1798 | 13 (7 distinct commanders) | 1, linking place 1740 (Aboukir Bay) | 1 | — |
  | 139, Miguel Enriquez's privateer fleet | 1 crewman | — | 33 | 40, the first dated `c.1704` | 1 | an Introduction |

### 3.3 Not-found and completeness

- **A missing fleet ID** returns a shell: the title is "Fleet details", the `h1` is empty, and the only table is a base table with empty Formed and Disbanded values. There is no ships table.
- **A missing fleet ID is not a redirect.** The probe's `final_url` in `_index.json` equals the request URL, unlike missing ships and actions, which 302. So the shell arrives directly, and there's no redirect case to handle in the spider or in `reparse.py`.
- **Every real page ends with `span#copywrite_message` and `</html>`.** A response without the footer is incomplete: `is_fleet_page` must require `common.has_footer` (S2), as `is_ship_page` does.

### 3.4 Data-quality signals (keep raw; never reconcile in the scraper)

- **Fleet dates are often year-only or approximate** (`1798`, `c.1704`). Keep the raw value and the precision.
- **Places are `show_shipyard` records** ("Aboukir Bay", 1740). There are no coordinates on fleet pages.
- **Ship joined and left dates may fall outside the ship's own lifecycle.** QA reports these; nothing is reconciled.
- **Ship pages already list their fleets.** Ship parser v4 reads the ship page's "Fleets" table into `ShipRecord.fleets` (`FleetRow.fleet_id`). That gives a second, request-free seed source, which also catches fleets the index might miss, and a symmetry check: ship X lists fleet F ↔ fleet F lists ship X.

## 4. Design

### 4.1 Items (in `items.py`)

```python
@dataclass
class FleetIndexRow:
    fleet_id: int | None
    name: str
    date_from: TDDate | None; date_to: TDDate | None
    nation_id: int | None; nation_text: str
    commander_ids: list[int]
    commanders: list[LinkRef]                         # hover-card lines in LinkRef.tooltip
    cells: list[str]                                  # lossless, the 5 cells' visible text

@dataclass
class FleetShip:
    td_id: int | None; ship_label: str                # "Orion (74)"
    ship: LinkRef | None                              # tooltip: ["1787-1814", "British 74 Gun", "3rd Rate Ship of the Line"]
    joined: TDDate | None; left: TDDate | None
    commander_ids: list[int]; commander_text: str | None
    commanders: list[LinkRef]
    notes: str
    cells: list[str]                                  # lossless, every td's visible text

@dataclass
class FleetEvent:
    date: TDDate | None
    text: str
    ship_ids: list[int]; place_ids: list[int]; battle_ids: list[int]   # IDs only (exact kind); never followed
    links: list[LinkRef]
    source_code: str | None

@dataclass
class FleetRecord:
    fleet_id: int
    name: str
    base_rows: list[BaseRow]                          # reuses the ship BaseRow, with source_code
    commander_ids: list[int]
    formed: TDDate | None; disbanded: TDDate | None
    introduction: str | None
    ships: list[FleetShip]; events: list[FleetEvent]
    sources: list[SourceRef]
    unknown_labels: list[str]; unknown_sections: list[str]
    url: str; fetched_at: str; content_sha256: str; parser_version: str
```

These follow ship parser v4's convention: visible text never contains hover-card text, and the hover card's lines survive in `LinkRef.tooltip` (`common.links`). Link IDs are always taken with `common.link_ids(node, kind)`, which matches the kind exactly. Fleet events link both ships and places, and a substring test would count `show_shipyard` links as `show_ship`.

### 4.2 State (additive)

```sql
CREATE TABLE IF NOT EXISTS fleets      (fleet_id INTEGER PRIMARY KEY, record_json TEXT NOT NULL,
                                        parser_version TEXT, content_sha256 TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS fleet_index (fleet_id INTEGER PRIMARY KEY, row_json TEXT NOT NULL);
```

The frontier rows live in Part A's `page_frontier`, under kind `fleet_index` (key `"1"`) and kind `fleet` (key = fleet ID).

- `save_fleet(record)` upserts the record and marks (`fleet`, id) `done` in **one** transaction.
- `save_fleet_index(rows)` upserts the rows and marks (`fleet_index`, "1") `done` in **one** transaction.

### 4.3 Spider flow

1. **The run** is `scripts/crawl.py --tiers <spider>`, which holds the crawl lock, watches the heartbeat and keeps the PC awake (6.0, S1). The spider itself takes no lock.
2. **Seed from ship records:** every `fleets[].fleet_id` already in stored ship records becomes a `fleet` row with `discovered_by='ship_fleets'`. This costs no requests.
3. **Seed** `fleet_index` "1". If it's pending, yield a GET of `show_fleetlist` at priority 10. Then stream the pending fleets in ascending ID order.
4. **Index callback:**
   - Run the completeness check.
   - Parse, then save the rows and mark the page `done` together.
   - Seed the fleet IDs (`discovered_by='fleet_index'`), and request only the **newly inserted** ones.
5. **Fleet page callback:** the shared `parse_entity_page` with the `FLEET` kind yields a `FleetRecord`, which the pipeline stores with `save_fleet`.

Errors, network outages, incomplete-page streaks, cool-offs and blocks behave exactly as for ships, because they come from the shared base (S4) and the unchanged middleware. Ship-record seeding reads the local `state.sqlite`, so run on the machine that holds the ship crawl's state if you want it.

### 4.4 Size and order

| Run | Requests | Time |
|---|---|---|
| E-smoke | index + 24 fleet pages (`-s CLOSESPIDER_PAGECOUNT=25`) | ~3–4 min |
| Tier E | 1 index GET + 146 fleet pages (+ any extra IDs from ship records) | ~20 min |

The delay is 6 s with ±1 s jitter, plus about 1.5 s per response: roughly 480 pages per hour.

The agreed run order is: ship smoke test → Tier A → actions → **fleets** → Tier C. The fleets crawl doesn't depend on any of the others, so it can run at any point when no other crawl is running.

## 5. Before you start

### 5.1 Read first

- **This plan:** all of it. Section 3 is the markup reference for every parser task.
- **The ship plan:** 2.3, 4.2, 4.3 and 6.
- **Code:**
  - `scrapers/threedecks/threedecks/`: `settings.py`, `politeness.py`, `middlewares.py`, `cache.py`, `lock.py`, `extensions.py`, `state.py`, `items.py`, `pipelines.py`, `spiders/base.py`, `spiders/ships_all.py`, `parsing/ship_page.py`, `parsing/grid.py`, `parsing/dates.py`
  - `scripts/`: every file
  - `tests/`: `test_spiders.py`, `test_state.py`, `test_middleware.py`, `test_resume.py`, `test_reparse.py`, `test_crawl.py`, `resume_harness.py`

### 5.2 Hard rules

1. **No network.** Never crawl threedecks.org, never run `scripts/fetch_fixtures.py`, and never fetch a Three Decks URL by any means. Every test runs offline, against fixtures or against `FakeSite` on 127.0.0.1. Live runs belong to the operator (section 9).
2. **Never loosen politeness.**
   - Don't change any setting in `threedecks.politeness.PROTECTED`, or `HTTPCACHE_*`, `DOWNLOADER_MIDDLEWARES`, `EXTENSIONS` or the `THREEDECKS_*` block and window settings.
   - Don't change the behaviour of `middlewares.py`, `cache.py`, `wba.py`, `extensions.py` or `lock.py`. New page kinds inherit all of it.
   - Don't define `custom_settings` on any spider.
   - Only the test harness may override the delay with `-s`, as it does today.
3. **Never commit scraped content.**
   - `tests/fixtures/real/` and `data/` stay gitignored.
   - Golden assertions go in test code.
   - Write synthetic fixtures by hand, kept minimal, from section 3. Never copy real HTML into them.
4. **No email addresses** in code, tests or docs. The contact comes from `THREEDECKS_CONTACT`; tests use `test@example.org`.
5. **Don't change the `frontier` or `ships` table schemas.**
6. **Keep it separate.**
   - Don't create, import or modify anything action-specific: `parsing/actions.py`, `spiders/actions.py`, `forms.py`, action items, action tables.
   - Shared files (`items.py`, `state.py`, `pipelines.py`, `resume_harness.py`, the scripts) only gain **additions**. Never restructure code the actions plan may also add to.
7. **TDD.** Write the failing test first, see it fail, then implement.
8. **Ship behaviour stays identical**, except where S1 says otherwise (`crawl.py` tiers, `fetch_fixtures.py` lock). An existing test may change only where a task lists the change.
9. **Stop and report rather than guess** if any of these happens:
   - a real fixture contradicts a number in section 3
   - an existing test needs an unlisted change
   - anything seems to need the network
   - the baseline doesn't match

### 5.3 Environment

- **Platform:** Windows 11, with Git Bash and PowerShell. Python ≥ 3.11 through `uv`.
- **Commands,** from the repo root: `uv run pytest -q`, `uv run pytest -q tests/test_x.py -k name` and `uv run ruff check`. The Three Decks tests alone: `uv run pytest -q --ignore=tests/shiplosses`.
- **Scrapy:** the project lives in `scrapers/threedecks/`. The resume harness runs `python -m scrapy crawl <spider>` from there.
- **Real fixtures:** in `tests/fixtures/real/`, with `_index.json`. `real_pages` tests skip themselves when the directory is absent.
- **Spider unit tests** build spiders without a crawler (`make()` in `tests/test_spiders.py`). Code that touches `self.crawler`, `self.settings` or stats must tolerate their absence. For stats tests, use `scrapy.utils.test.get_crawler`.
- **Git:** work on branch `data-layout`. Commit after each task: `Three Decks S<n>: <title>` for Part A, `Three Decks fleets FL<n>: <title>` for Part B. Never push.

### 5.4 Baseline and Task 0

- **Before Part A** (measured 2026-10-08, after merge 2f63489): `uv run pytest -q` gives **488 passed, 2 failed, 2 skipped, 68 deselected** (deselected = network-marked), and `uv run ruff check` is clean.
- **The 2 failures are known and unrelated:** `tests/shiplosses/test_extractors.py::test_golden_extractor_outputs` and `tests/shiplosses/test_extractors_phase4.py::test_golden_counts_phase4` need raw UKHO and INFOMAR files under `data/raw/` that aren't on every machine. Everywhere this plan says "green", it means: no new failures, and those two may fail only for that reason.
- **If Part A is already done**, because the actions plan ran first: there are more tests, and all of them must pass.

**Task 0.** Run the baseline. The plans and the recon fixture list are already committed (5cb05ac). If `git status` shows uncommitted changes under `docs/plans/` or in `scripts/fetch_fixtures.py`, stop and ask; don't commit someone else's work in progress.

## 6. Part A: shared foundation (tasks S1–S4)

**This part is identical in the actions plan and the fleets plan.** Whichever plan is executed first does it; the other one skips it.

**Skip check:** Part A is done if `git log --oneline` shows the four commits "Three Decks S1:" through "Three Decks S4:", and the Three Decks tests pass (5.4). If so, go straight to Part B. If only some S-commits exist, continue from the first one missing.

### 6.0 Already in the code: don't redo

Commit e9ec193 ("Harden the Three Decks crawler", 2026-10-05) already delivers most of what an earlier draft of this part asked for. Reuse it and don't rebuild it:

- **Cloudflare handling** (`middlewares.py`).
  - The passive `/cdn-cgi/challenge-platform/scripts/jsd/main.js` beacon on every page is **not** a challenge.
  - A 429 or a challenge **pauses** the crawl (15/30/60 min, or `Retry-After`) and retries the same request unchanged.
  - A 403 or a WAF block page ("Sorry, you have been blocked", `cf-mitigated: blocked`) closes the spider `blocked`, and so do 4 blocks inside 2 h.
  - Blocks raise `IgnoreRequest`, so neither a callback nor an errback ever sees them.
- **Cache** (`cache.py`).
  - Challenge pages, block pages, robots.txt and retried statuses are never cached.
  - Bodies are stored still encoded (the site serves zstd), so anything reading the cache outside Scrapy must use `load_cached_response`.
  - Redirects are cached as the 302 itself.
- **Rate** (`settings.py`).
  - `DOWNLOAD_DELAY = 6` with `DOWNLOAD_DELAY_JITTER = 1/6`, so gaps run 5.0 to 7.0 s. Retries cover 5xx and Cloudflare's 52x and 530.
  - `politeness.PROTECTED` lists the settings that `crawl.py -s` refuses to override against the real site.
- **Lock** (`lock.py`). `CrawlLock(path)` is a context manager holding an OS lock; contention raises `CrawlLockHeld(pid, started)`.
  - **`scripts/crawl.py` and `scripts/smoke.py` hold it. The spiders don't**, so a plain `scrapy crawl` against the real site is not locked. Live runs go through `crawl.py` (section 9).
- **Base spider** (`spiders/base.py`), for ships:
  - **Errback** (`on_ship_error`): an `HttpError` marks `error` and counts an attempt; an `IgnoreRequest` leaves the state alone; no response at all goes to a network-failure streak, which closes `network_down` and gives the attempts back (`release_attempts`).
  - **Incomplete pages:** 3 distinct incomplete pages in a row close `incomplete_streak`.
  - **Parse errors:** a parser exception marks `parse_error` and the crawl moves on.
  - **Provenance:** `fetched_at` comes from `cache_timestamp` on a cache replay.
  - **Dedupe:** each ID is requested once per run (`ship_requests`, `_requested`).
  - **Stats:** `threedecks/not_found`, `fetch_error`, `incomplete_page`, `parse_error`, `unknown_label/<label>` and `unknown_section/<heading>`.
  - **Runs:** `runs.pages_fetched` counts live fetches only.
  - **Contact:** `require_contact` refuses to start without `THREEDECKS_CONTACT`.
- **Ship parser v4** (`parsing/ship_page.py`).
  - `is_ship_page` requires the footer `span#copywrite_message`.
  - Visible text and links skip hover cards (`_VISIBLE_TEXT`, `_VISIBLE_LINKS`). The hover card's lines are kept in `LinkRef.tooltip`.
  - `_link_ids(node, kind)` matches the link kind **exactly**, because `show_ship` is a prefix of `show_shipyard`.
  - `_parse_fleets` reads a table whose body has no `<tr>` (ship pages' "Fleets" table, `FleetRow.fleet_id`).
- **Dates** (`parsing/dates.py`). `parse_td_date` already accepts the qualifiers `bef.`, `aft.` and `c.`.
- **Driver** (`scripts/crawl.py`, `scripts/crawl_all.py`).
  - Tiers run as `scrapy crawl` subprocesses, under a heartbeat watchdog, with keep-awake, logs in `data/threedecks/logs/`, network retries, and an optional daily budget and crawl window.
  - `crawl.TIERS = ("captures", "ships_by_nation", "ships_all")`. `crawl_all.py` runs until every one of `TIERS` has finished.

### Task S1: Close the lock gaps; let `crawl.py` run non-ship tiers

Ship-plan rule 10 says every live crawl holds `data/threedecks/crawl.lock`, but `fetch_fixtures.py` doesn't yet. The actions and fleets crawls must also run under `crawl.py`, because that's where the lock, the watchdog and the logs are. But `crawl.py` is ship-shaped.

- **Files:** `scripts/fetch_fixtures.py`, `scripts/crawl.py`, `tests/test_fetch_fixtures.py`, `tests/test_crawl.py`.
- **`fetch_fixtures.py`:** wrap the fetch loop in `CrawlLock(DATA_DIR / "crawl.lock")`, using `threedecks.settings.DATA_DIR`. On `CrawlLockHeld`, print the holder and return 2, as `crawl.py` does.
- **`crawl.py`:**
  - Add `EXTRA_TIERS: tuple[str, ...] = ()`. Each Part B appends its spider's name. Neither Part B edits the other's entry.
  - `--tiers` accepts names from `TIERS + EXTRA_TIERS`, but its default stays `TIERS`. So `crawl_all.py` and a bare `crawl.py` never run actions or fleets.
  - The ship-target logic applies **only to tiers in `TIERS`**: the `ship_count >= args.ships` check before a tier, the `THREEDECKS_SHIP_TARGET` setting and `SHIP_TARGET_REASON`. An extra tier runs whatever the ship count is.
  - A tier that closes `closespider_pagecount` (a smoke run with `-s CLOSESPIDER_PAGECOUNT=25`, which isn't a protected setting) ends the chain with status 0 and the verdict "page cap reached during <spider>", not "closed with reason …".
- **Tests first:**
  - **`fetch_fixtures` lock:** while the test holds `CrawlLock` on a temp data dir (`THREEDECKS_DATA_DIR`), `main([])` returns 2 and makes no request. Monkeypatch `httpx.Client` to fail if it's constructed.
  - **`crawl.py` tiers:** with `EXTRA_TIERS` monkeypatched to `("dummy",)`, `--tiers dummy` parses; an unknown name is still rejected; the default `--tiers` equals `TIERS`.
  - **Ship target:** with `run_tier` monkeypatched, a stored ship count above `--ships` doesn't skip `dummy`, and `dummy`'s command carries no `THREEDECKS_SHIP_TARGET`. Follow the existing `tests/test_crawl.py` patterns.
  - **Page cap:** a `closespider_pagecount` close returns status 0.
- **Done when:** green, and every existing `test_crawl.py`, `test_crawl_all.py` and `test_smoke.py` test still passes.

### Task S2: `parsing/common.py`

A pure refactor, so the action and fleet parsers can share the ship parser's text and link helpers.

- **Files:** `parsing/common.py` (new), `parsing/ship_page.py`, `tests/test_common.py` (new).
- **Move** these from `ship_page.py` into `common.py` under public names, and have `ship_page.py` import them:

  | In `ship_page.py` | In `common.py` |
  |---|---|
  | `_norm` | `norm` |
  | `_kind` | `link_kind` |
  | `_tooltip_lines` | `tooltip_lines` |
  | `_links` | `links` |
  | `_link_ids` | `link_ids` |
  | `_node_text` | `node_text` |
  | `_int_from_text` | `int_from_text` |
  | `_parse_sources` | `parse_sources` |
  | `_NOT_TOOLTIP`, `_VISIBLE_TEXT`, `_VISIBLE_LINKS` | `NOT_TOOLTIP`, `VISIBLE_TEXT`, `VISIBLE_LINKS` |

  Grep `tests/` and `scripts/` for every private name imported from `ship_page`, and keep an alias for each one.
- **Add:**
  - `has_footer(sel) -> bool`, the footer half of `is_ship_page`. `is_ship_page` then uses it, with identical behaviour.
  - `visible_text(node, *, drop_hidden=False) -> str`, which equals `node_text`. With `drop_hidden=True`, it also skips text inside `span.hidden`: action participant cells start with `<span class="hidden">Name : </span>`.
- **Tests first:**
  - `visible_text` on a synthetic tooltip snippet returns only the anchor text. `drop_hidden=True` removes "Name :".
  - `link_ids(node, "show_ship")` ignores a `show_shipyard` link.
  - `has_footer` gives True and False.
- **Done when:** every ship parser test passes **unchanged**.

### Task S3: Generic page frontier

The ship `frontier` table is keyed by `td_id`. Action and fleet IDs are separate ID spaces (battle 157 is not ship 157). Changing `frontier`'s primary key would mean rebuilding a table the ship spiders depend on, so this task adds a separate table, created with `CREATE TABLE IF NOT EXISTS`. That's safe even while a ship crawl's state file is in use.

- **Files:** `state.py`, `tests/test_state.py`.
- **Schema:** append to `_SCHEMA`:

  ```sql
  CREATE TABLE IF NOT EXISTS page_frontier (
      kind TEXT NOT NULL,          -- e.g. 'action', 'action_index', 'fleet', 'fleet_index'
      page_key TEXT NOT NULL,      -- entity id or index page number, as text
      discovered_by TEXT,
      depth INTEGER NOT NULL DEFAULT 0,
      status TEXT NOT NULL DEFAULT 'pending',   -- pending | done | not_found | error | parse_error
      attempts INTEGER NOT NULL DEFAULT 0,
      http_status INTEGER, last_error TEXT, updated_at TEXT,
      PRIMARY KEY (kind, page_key)
  );
  CREATE INDEX IF NOT EXISTS page_frontier_status ON page_frontier (kind, status);
  ```

- **Methods:**

  ```python
  seed_pages(kind, keys, discovered_by, depth=0) -> list[str]   # newly inserted keys, input order
  pending_pages(kind, max_attempts=3) -> Iterator[str]          # pending/error with attempts < max,
                                                                # ORDER BY CAST(page_key AS INTEGER), page_key
  page_status(kind, key) -> str | None
  page_attempts(kind, key) -> int
  mark_page_status(kind, key, status, *, http_status=None, error=None,
                   increment_attempts=False, discovered_by=None, depth=0) -> None
  release_page_attempts(kind, keys, reason="network down; attempt not counted") -> None
                                                                # mirror of release_attempts
  page_counts_by_status(kind) -> dict[str, int]
  _page_done_sql(kind, key, now) -> None   # executes the "mark done" upsert WITHOUT committing, so a
                                           # kind-specific save_*() can write record + done in ONE transaction
  ```

  - `counts_by_status()`, `release_attempts()` and everything else that's ship-only stay unchanged.
  - `close_open_runs()` estimates an interrupted run's end from `MAX(updated_at)` across **both** `frontier` and `page_frontier`. Today it reads only `frontier`, so an interrupted actions run would get a wrong end time.
- **Tests first:**
  - Seeding is idempotent, and `seed_pages` returns only the new keys.
  - Numeric order: "10" comes after "9".
  - Namespaces are separate: ship 157 `done`, page (x, "157") still `pending`.
  - Attempts count up and cap. `release_page_attempts` gives one back and resets the status to `pending`.
  - `close_open_runs` uses a `page_frontier` update time.
  - Reopening keeps everything.
  - **Old schema:** build `state.sqlite` with a copy of the pre-S3 `_SCHEMA` text (paste it into the test as `OLD_SCHEMA`), insert a ship and a frontier row, then open it with the new `StateStore`. Both rows are intact and `page_frontier` exists.
- **Done when:** green, and every existing state test is unchanged.

### Task S4: `PageKind` registry and a kind-agnostic base

The base spider's ship path already carries the behaviour the new crawlers need: the errback semantics, the network streak, the incomplete streak, parse errors, the per-run dedupe and cache-replay provenance. This task makes that path work for any page kind. **Ship behaviour, stat keys and tests don't change.**

- **Files:** `threedecks/pages.py` (new), `spiders/base.py`, `tests/resume_harness.py`, `tests/test_spiders.py`.
- **`pages.py`:**

  ```python
  @dataclass(frozen=True)
  class PageKind:
      name: str                                  # 'ship', later 'action' / 'fleet'
      display_type: str                          # 'show_ship', later 'show_battle' / 'show_fleet'
      is_page: Callable[[Selector], bool]        # must include the footer check (common.has_footer)
      is_not_found: Callable[[Selector], bool]
      parse: Callable[..., object]               # (selector, url, *, fetched_at, content_sha256, parser_version)
      parser_version: str
  KINDS: dict[str, PageKind] = {}
  def register(kind: PageKind) -> PageKind: ...  # KINDS[kind.name] = kind; idempotent
  SHIP = register(PageKind("ship", "show_ship", is_ship_page, is_not_found_page, parse_ship, PARSER_VERSION))
  ```

  Each Part B registers its own kind in its own module. Neither Part B edits the other's kind.
- **Base (`TDSpider`):** generalise, keeping the ship names as thin wrappers:
  - `entity_url(kind, id)` builds `f"{base_url}/index.php?display_type={KINDS[kind].display_type}&id={id}"`.
  - `entity_requests(kind, ids, *, depth=0, discovered_by=None, priority=0)` dedupes per run per `(kind, id)`, as `ship_requests` does. Each request's meta holds `{kind, key, depth, discovered_by}` (plus `td_id` for ships), with `errback=self.on_entity_error` and `dont_filter=True`.
  - `parse_entity_page(response)` checks, in order: not-found, then completeness (`is_page`, which includes the footer), then parse in try/except, then stats.
    - **Take the key from `response.meta["key"]`, not from the URL.** A missing ID can come back as a redirect, and then `response.url` is the redirect target (the actions plan's 3.3).
    - `fetched_at` comes from `cache_timestamp` when the page was replayed from the cache.
  - `on_entity_error(failure)` keeps `on_ship_error`'s semantics: `HttpError` → `error` plus an attempt; `IgnoreRequest` → leave the state alone; no response → network streak.
  - The network streak and the incomplete streak hold `(kind, key)` pairs. `release_attempts` routes to `store.release_attempts` (ship) or `store.release_page_attempts` (others).
  - `_mark(kind, key, status, **kw)` routes to `store.mark_status(int(key), …)` (ship) or `store.mark_page_status(kind, key, …)` (others).
  - `stream_pending_pages(kind)`.
  - **Stats:** ship keys stay exactly as they are (`threedecks/not_found`, …). Every other kind uses `threedecks/<kind>/not_found`, `fetch_error`, `incomplete_page`, `parse_error`, `unknown_label/<label>`, `unknown_section/<heading>`.
  - `ship_url`, `ship_request(s)`, `parse_ship_page`, `on_ship_error` and `stream_pending` remain as ship wrappers, so `ShipsAllSpider`, `CapturesSpider`, `ShipsByNationSpider` and every existing test work unchanged.
- **Harness:**
  - `run_crawl(..., spider="ships_all")` and `start_crawl(..., spider="ships_all")`. Existing callers are unchanged.
  - Refactor `FakeSite`'s `do_GET` and `do_POST` to dispatch on `display_type` through `self.get_handlers` and `self.post_handlers` (`dict[str, Callable]`). The ship and captures handlers are registered by default and behave exactly as now.
  - Count requests per `(display_type, key)`. Keep `count(td_id)` and `total_ship_requests` as ship wrappers.
  - Add `blocked: set[tuple[str, str]]` (answered with 429) and keep `block_id`, `block_active`, `block_limit`, `drop_ships` and `hang_secs` working for ships.
  - Each Part B adds its handlers in its own helper function, never by editing the other's.
- **Tests first:**
  - `entity_requests("ship", [5])` equals `ship_requests([5], …)` in URL and meta.
  - `parse_entity_page` with the ship kind behaves exactly like `parse_ship_page` on the synthetic fixtures: done, not_found, incomplete and parse_error.
  - A response whose `url` differs from the request (a simulated redirect) is recorded under `meta["key"]`.
  - The `FakeSite` handler registry serves ships and captures exactly as before.
- **Done when:** green, and every existing spider, resume, crawl and smoke test is unchanged.

## 7. Part B: the fleets crawler (tasks FL1–FL9)

Each task lists its files, the tests to write first, implementation notes, and its exit criterion ("Done when").

### Task FL1: Fleet date forms (tests only)

`parse_td_date` already accepts `D.M.YYYY`, `M.YYYY`, `YYYY`, `YYYY/MM/DD` and the qualifiers `bef.`, `aft.` and `c.` (6.0). Fleet pages need nothing new. This task pins the forms they use, so a future change can't break them silently.

- **Files:** `tests/test_dates.py` (additions only).
- **Tests (parametrised):**

  | Input | Qualifier | ISO | Precision |
  |---|---|---|---|
  | `c.1704` | `"c."` | `"1704"` | year |
  | `2.1501` | — | `"1501-02"` | month |
  | `1798/08/14`, tooltip `Tuesday 14th of August 1798` | — | `"1798-08-14"` | day (tooltip kept raw) |
  | `14.8.1798`, tooltip `14th August 1798` | — | `"1798-08-14"` | day |

- **If any case fails,** stop and report rather than change `dates.py`. The ship parser depends on it.
- **Done when:** green.

### Task FL2: Fleet items

- **Files:** `items.py` (additions only), `tests/test_items_fleets.py` (new).
- Add the section 4.1 dataclasses: `FleetIndexRow`, `FleetShip`, `FleetEvent` and `FleetRecord`. Reuse the existing `LinkRef` (with its `tooltip` field), `BaseRow`, `TDDate` and `SourceRef`.
- **Don't rename or touch the existing `FleetRow`.** It's the ship page's "Fleets" table row.
- **Test:** each type survives a round trip through `dataclasses.asdict` and `json.dumps`.
- **Done when:** green.

### Task FL3: Fleet parsers

- **Files:** `parsing/fleets.py` (new), `tests/test_fleets.py` (new). New synthetic fixtures: `tests/fixtures/synthetic/fleetlist_index.html`, `fleet_full.html`, `fleet_notfound.html` and `fleet_truncated.html`.
- **Use the S2 helpers only:** `common.visible_text`, `common.links`, `common.link_ids`, `common.parse_sources` and `common.has_footer`. Don't write new text or link extraction.
- **API:**

  ```python
  FLEET_PARSER_VERSION = "1"
  def is_fleet_page(sel) -> bool            # non-empty h1, a table.column8 whose first-cell labels include
                                            # "Fleet Formed", and common.has_footer
  def is_fleet_not_found(sel) -> bool       # <title> == "Fleet details" (stripped, case-insensitive) and h1 empty
  def is_fleetlist_index_page(sel) -> bool  # an h1 "Fleets", at least one show_fleet link in #datacol, and has_footer
  def parse_fleet_index(sel) -> list[FleetIndexRow]
  def parse_fleet(sel, url, *, fetched_at="", content_sha256="", parser_version=FLEET_PARSER_VERSION) -> FleetRecord
  ```

- **Index:**
  - Take the cells as `(//div[@id='datacol']//table)[1]/tbody/td | …/tbody/tr/td`, in document order. This keeps working if the site ever adds `tr` rows.
  - Chunk them in fives, in the order of section 3.1. Follow the pattern of the ship parser's `_parse_fleets`, which reads the same `tr`-less markup.
  - Dates go through `parse_td_date(text, title)`. `nation_id` is None when the cell is text.
  - `commanders` is `common.links` of the commander cell, filtered to `show_crewman`. `cells` holds each cell's `visible_text`.
  - If the cell count isn't a multiple of 5, parse the complete rows, then raise `ValueError`, so the spider records `parse_error`.
- **Fleet page,** scoped to `div#datacol`. Classify every `table.column8` that isn't `#comment_list_table`:
  - **Base table** (its first-cell labels include "Fleet Formed"):
    - Each row becomes a `BaseRow`: label from the first `td`; text from the other non-`source_col` cells' `visible_text`; `date` from a `span[@title]` through `parse_td_date`; `links` from `common.links`; `source_code` from `td.source_col a`.
    - Labels outside {Fleet Commander, Fleet Formed, Fleet Disbanded} go to `unknown_labels`.
    - `commander_ids` come from the Fleet Commander row's `link_ids(…, "show_crewman")`; `formed` and `disbanded` come from their rows' dates.
  - **Ships table** (its `th` texts include "Ship" and "Joined"). Each data row becomes a `FleetShip`; pick cells by class and content, never by position:
    - `ship` is the first `common.links` entry of kind `show_ship` in the row; `td_id` and `ship_label` are its `id` and `text`.
    - `joined` and `left` come from the first and second `td.column1` in the row.
    - The commander comes from the `td.column2` holding a `show_crewman` link: `commanders`, `commander_ids` and `commander_text`. Without one, the lists are empty, and `commander_text` is None when that cell is nbsp.
    - `notes` is the last `td.column2`'s `visible_text`, and `cells` holds every `td`'s `visible_text`.
  - **Events table** (its header includes "Date" and "Event"). Each data row becomes a `FleetEvent`:
    - The date is `parse_td_date(text, title)` when there's a `span.date_field`, otherwise `parse_td_date(text)`, which covers `c.1704`.
    - `text` is `td.col_info_text`'s `visible_text`, and `links` is its `common.links`.
    - `ship_ids`, `place_ids` and `battle_ids` come from `link_ids` with `show_ship`, `show_shipyard` and `show_battle`.
    - `source_code` comes from `td.source_col a`, or None.
  - **Any other `table.column8`:** `unknown_sections.append("table: " + first header text)`.
  - **`introduction`:** the `p` text after an `h2` "Introduction", up to the next `table` or `h2`.
  - **Any other `h2`** (not Introduction, Sources or "Recent comments to other pages") goes to `unknown_sections`.
  - **`sources`:** `common.parse_sources`. **`fleet_id`:** `extract_id(url)`.
- **Synthetic fixtures,** with the footer `<span id="copywrite_message">Copyright</span>` on every page except the truncated one:
  - **`fleetlist_index.html`:** a flat `tbody` with 3 fleets: one with nation "Unknown?", one with no commander, and one with a tooltip commander.
  - **`fleet_full.html`:**
    - a base table with sources, plus one unknown label
    - a ships table with one 7-cell row with a commander and one without
    - an events table with a `date_field` row, a `c.1704` row, and a row linking a ship, a place and a battle
    - an Introduction
    - a comment table with `show_ship` links
  - **`fleet_notfound.html`:** the empty shell from 3.3.
  - **`fleet_truncated.html`:** `fleet_full.html` cut before the footer.
- **Golden tests** (`real_pages`), from section 3:
  - **`fleetlist_index`:** 146 rows; 146 unique IDs; min 1, max 151. Row 1 is `fleet_id` 132, nation text "Unknown?", `nation_id` None, no commander, `date_from` raw "2.1501". `nation_id` 7 rows are fleets {139, 146, 151}.
  - **97:**
    - name "Saumarez's Squadron 1798"; commander [4757]; formed 1798-08-14; disbanded "1798" (year)
    - 13 ships; the first ship is Orion with `ship.tooltip == ["1787-1814", "British 74 Gun", "3rd Rate Ship of the Line"]`
    - 1 event with `place_ids == [1740]` and `ship_ids == []`. Aboukir Bay is a shipyard link, not a ship.
    - 1 source; `unknown_labels == []` and `unknown_sections == []`
  - **139:** 33 ships; 40 events; the first event's raw date is "c.1704" with qualifier "c."; introduction not None; 1 source; no `unknown_*`.
  - **`fleet_notfound_probe`:** `is_fleet_not_found` is True and `is_fleet_page` is False.
  - **No leaks:** no **visible** text field (`ship_label`, `commander_text`, `notes`, event `text`) contains "Naval Sailor". That text belongs in `LinkRef.tooltip`.
  - **Cross-check with ship parser v4:** the synthetic `tests/fixtures/synthetic/ship_full.html` lists fleet 139 in its "Fleets" table (`test_fleets_table_without_row_tags`). Assert that `parse_fleet` on `fleet_139.html` returns `fleet_id == 139`.
- **Done when:** green.

### Task FL4: Fleet state

- **Files:** `state.py` (additions only), `tests/test_state_fleets.py` (new).
- **Schema:** add the section 4.2 DDL to `_SCHEMA`.
- **Methods:**

  ```python
  save_fleet(record: FleetRecord) -> None                     # upsert + _page_done_sql('fleet', str(id)), one transaction
  save_fleet_index(rows: list[FleetIndexRow]) -> int          # upsert rows with an id + ('fleet_index', '1') done; returns rows stored
  get_fleet(fleet_id) -> dict | None
  iter_fleets(); iter_fleet_index(); fleet_count() -> int
  ship_fleet_ids() -> list[int]                               # sorted unique fleets[].fleet_id across ship records
  ```

- **Tests first:**
  - `save_fleet` writes the record and `done` together.
  - `save_fleet_index` skips rows without an ID and marks the index `done`.
  - Ship 97 and fleet 97 don't interfere.
  - `ship_fleet_ids` returns the IDs from saved ship records.
  - Reopening keeps everything.
- **Done when:** green.

### Task FL5: `FLEET` kind and pipeline

- **Files:** `parsing/fleets.py` or a new `threedecks/kinds_fleets.py`, `pipelines.py` (additions only), `tests/test_pipelines.py`.
- **The kind:** `FLEET = register(PageKind("fleet", "show_fleet", is_fleet_page, is_fleet_not_found, parse_fleet, FLEET_PARSER_VERSION))`. Make sure it's registered whenever the spiders module loads.
- **Validation:** drop a `FleetRecord` without a `fleet_id` or a `name`.
- **Storage:** `StatePipeline` routes `FleetRecord` to `save_fleet`.
- **Index rows are not items.** The spider stores them with `save_fleet_index`.
- **Tests:** mirror the ship pipeline tests.
- **Done when:** green.

### Task FL6: The `fleets` spider

- **Files:** `spiders/fleets.py` (new), `tests/test_spiders_fleets.py` (new).
- **Spider:**

  ```python
  class FleetsSpider(TDSpider):
      name = "fleets"
      default_max_depth = 0
      def start_requests(self):
          self.store.seed_pages("fleet", [str(i) for i in self.store.ship_fleet_ids()],
                                discovered_by="ship_fleets")
          self.store.seed_pages("fleet_index", ["1"], discovered_by="start")
          if self.store.page_status("fleet_index", "1") in ("pending", "error") \
                  and self.store.page_attempts("fleet_index", "1") < self.max_attempts:
              yield self.index_request()                         # priority=10
          yield from self.stream_pending_pages("fleet")
      def index_request(self): ...   # GET {base}/index.php?display_type=show_fleetlist,
                                     # meta kind='fleet_index', key='1', errback=self.on_entity_error,
                                     # dont_filter=True, priority=10
      def parse_index(self, response): ...
  ```

- **`parse_index`:**
  1. **Completeness:** `is_fleetlist_index_page` (which includes the footer). If it fails, take the base's incomplete path (S4): drop the cache entry, mark `error`, retry once, and count towards the incomplete streak.
  2. **Parse** in try/except, recording `parse_error` (`threedecks/fleet_index/parse_error`).
  3. **Store:** `save_fleet_index(rows)`.
  4. **Fleets:** `seed_pages("fleet", ids, discovered_by="fleet_index")`. Yield `entity_requests("fleet", new_ids)` for **newly inserted** keys only.
  5. **Stats:** `threedecks/fleet_index/rows` and `threedecks/fleet_index/row_without_id`.
- **Fleet pages** go through `parse_entity_page` with the `FLEET` kind.
- **Tests first:**
  - On an empty store, `start_requests` yields exactly one GET, to `show_fleetlist`.
  - **Ship-record seeding:** save a ship whose `fleets` list fleet 139. `start_requests` yields the index request, then a request for fleet 139.
  - **`parse_index` on synthetic `fleetlist_index.html`:** the rows are stored, the index is `done`, and each fleet is requested once. A second call yields no requests.
  - When the index is already `done`, `start_requests` yields only the pending fleet requests.
  - **Not found:** `fleet_notfound.html` → (`fleet`, id) `not_found`.
  - **Truncated:** `fleet_truncated.html` → `error`, one retry, `threedecks/fleet/incomplete_page`.
  - **Separation:** collect every request from `start_requests`, `parse_index` and `parse_entity_page` over all the synthetic fleet fixtures. For each one, `parse_qs(urlparse(url).query)["display_type"]` is exactly `["show_fleetlist"]` or `["show_fleet"]`. In particular, there's no `show_battle`, although `fleet_full.html` links a battle in an event. Compare exactly, not by substring.
  - `FleetsSpider` defines no `custom_settings`.
- **Done when:** green.

### Task FL7: Resume and lock tests

- **Files:** `tests/resume_harness.py` (an `add_fleet_routes(site, fleet_ids)` helper, additions only), `tests/test_resume_fleets.py` (new).
- **The routes:**
  - **GET `show_fleetlist`:** a flat-cell index in the 3.1 markup, with the footer.
  - **GET `show_fleet`:** a minimal fleet page (`h1`, a base table with "Fleet Formed", a ships table with one ship, the footer), or the "Fleet details" shell for unknown IDs. A 200, not a redirect: that's how the real site answers.
- **The harness** already sets `THREEDECKS_MAX_COOLOFFS=0`, so a 429 closes `blocked` at once.
- **Tests** (mirror `tests/test_resume.py`):
  - **Graceful stop:** 60 fleets plus 1 unknown ID seeded from a ship record.
    - The first run stops with `CLOSESPIDER_ITEMCOUNT=20`, and a rerun completes.
    - Every fleet is `done` once, and the unknown ID is `not_found`.
    - The server saw the index once and each fleet once, and the export has 60 unique fleets.
  - **Hard kill:** `proc.kill()` after 20 items, then a rerun. At most one fleet is fetched twice.
  - **Truncated cache entry:** plant a footer-less body for one fleet. The rerun refetches it, and the record is complete.
  - **Blocked:** a 429 on fleet 30 closes the run as `blocked`. After the block clears, a rerun completes, and the index isn't refetched.
  - **Cool-off:** one 429 with `-s THREEDECKS_MAX_COOLOFFS=2 -s THREEDECKS_COOLOFF_SECS=1`. The crawl pauses, retries the same request once, and completes.
  - **Crawl lock (through `crawl.py`):** while the test holds `CrawlLock(data / "crawl.lock")`, run `python scripts/crawl.py --tiers fleets --allow-sleep --pause-seconds 0 -s DOWNLOAD_DELAY=0 -s DOWNLOAD_DELAY_JITTER=0 -s AUTOTHROTTLE_ENABLED=False -s THREEDECKS_MAX_COOLOFFS=0` in a subprocess. Point `THREEDECKS_BASE_URL` at `FakeSite` and `THREEDECKS_DATA_DIR` at `data`, and set `THREEDECKS_CONTACT`; protected overrides are allowed against a local site. It exits 2, and the site saw **zero** requests. Release the lock, and the same command completes the crawl.
  - **Namespaces:** ship 97 and fleet 97 both exist. Run `ships_all`, then `fleets`. Both are stored, and both frontier rows are `done`.
- **Done when:** green. Keep the new tests under about 2 minutes in total.

### Task FL8: Driver, scripts and recipes

All changes are additions. Don't restructure what the ship code or the actions plan has, or will have.

- **`scripts/crawl.py`:** append `"fleets"` to `EXTRA_TIERS` (S1). `crawl_all.py` doesn't change.
- **`justfile`:** add two recipes:

  ```
  # Three Decks fleet lists crawl (~20 min; separate from the ship tiers); rerun to resume
  threedecks-fleets *args:
      uv run python scripts/crawl.py --tiers fleets {{ args }}

  # Fleets smoke test: 25 pages (~4 min)
  threedecks-fleets-smoke *args:
      uv run python scripts/crawl.py --tiers fleets -s CLOSESPIDER_PAGECOUNT=25 {{ args }}
  ```

- **`crawl_status.py`:** a "fleets" block giving the `fleet_index` and `fleet` status counts, the fleets stored, and the last `fleets` run with its ETA.
- **`reparse.py`:**
  - If `--kind` doesn't exist yet, add it, with `ship` and `all` among the choices. Then add `fleet` and `fleet_index`.
  - Read the cache only through `load_cached_response`. The bodies are zstd-encoded.
  - `show_fleet` URLs are reparsed with `parse_fleet`, and `show_fleetlist` with `parse_fleet_index`.
  - The not-found and completeness rules are the spider's. No network.
- **`export.py`:** adds five files.
  - `fleets.jsonl` and `fleet_index.jsonl`.
  - `fleets.parquet`: `fleet_id`, `name`, `nation_id` (joined from the index), `commander_ids`, `formed_iso`, `disbanded_iso`, `ship_count`, `event_count`, `url`, `fetched_at`, `content_sha256` and `parser_version`.
  - `fleet_ships.parquet`: `fleet_id`, `td_id`, `ship_label`, `ship_tooltip` (joined with " | "), `joined_iso`, `left_iso`, `commander_ids` and `notes`.
  - `fleet_events.parquet`: `fleet_id`, `date_raw`, `date_iso`, `text`, `ship_ids`, `place_ids`, `battle_ids` and `source_code`.
- **`qa_report.py`:** a "Fleets" section, in both the Markdown and the JSON output. It counts:
  - index IDs not fetched, and fetched IDs (found through ship records) missing from the index
  - symmetry with ship records: ship X's `fleets` lists fleet F, but F's `ships` lack X, and the reverse
  - fleet ships with no `td_id`, and fleet ships not found in `ships`
  - fleet ships whose joined or left date falls outside the ship's lifecycle (Launched to its last fate date)
  - `unknown_labels` and `unknown_sections`
  - frontier errors for the `fleet` and `fleet_index` kinds
- **Tests:**
  - **Export:** from a state DB holding two synthetic fleet records, the files exist, the row counts match, and every ship and event row has its `fleet_id`.
  - **QA:** a prepared asymmetry (a ship's `fleets` cites fleet 5, whose `ships` lack the ship) and a prepared out-of-lifecycle fleet ship are both reported.
  - **Reparse:** a cache DB written with `SqliteCacheStorage`, holding one zstd-encoded fleet page, gives a stored record. Mirror `tests/test_reparse.py`.
  - **Status:** the output contains the fleets block.
  - **Driver:** `--tiers fleets` is accepted, and the default tiers still exclude it.
- **Done when:** green.

### Task FL9: Docs and final check

- **Ship plan, section 4 tree:** add `pages.py`, `parsing/common.py`, `parsing/fleets.py` and `spiders/fleets.py`, unless they're already there.
- **Final check:** `uv run ruff check` clean, and `uv run pytest -q` green in the sense of 5.4. Then report back (section 8).

## 8. Report back

When finished, or when stopped by a rule in 5.2, report:

- one line per task (S1–S4, FL1–FL9): done / skipped (already done) / blocked, and its commit hash
- the final `pytest` summary line and the `ruff` result
- any deviation from this plan, with the reason
- any real-fixture number that disagreed with section 3
- open questions for the operator

## 9. Operator runbook (human only; not for the agent)

Run from the repo root, in a **new** terminal so the `THREEDECKS_CONTACT` user variable is visible. For ship-record seeding, run on the machine that holds the ship crawl's `data/threedecks/`. The index alone also covers all 146 fleets.

- **Locking:** every command below goes through `scripts/crawl.py` or `scripts/smoke.py`, which hold the crawl lock. A second crawl refuses to start. Never run `scrapy crawl` by hand against the site.
- **Blocks:** a 429 or a challenge pauses the crawl for 15/30/60 min. A `blocked` close means stop and contact the owner (rule 5).

1. **Ship smoke test,** if the ship crawler hasn't run on this machine yet: `just threedecks-smoke`.
2. **Fleets smoke test:** `just threedecks-fleets-smoke`.
   - It ends with "page cap reached during fleets".
   - The closing stats must show no `threedecks/fleet/parse_error`, `incomplete_page`, `unknown_label` or `unknown_section`.
   - Then run `just threedecks-fleets`, press Ctrl+C after about 10 pages, and run it again. It must continue where it stopped.
3. **Tier E:** `just threedecks-fleets` (about 20 min). Then:
   - `uv run python scripts/crawl_status.py`
   - `uv run python scripts/qa_report.py --out data/threedecks/exports/qa.md`
4. **After the ship crawl's Tier C (optional):** `just threedecks-fleets --rerun`. It fetches only fleet IDs that newly crawled ships cite and the index lacked.
5. **Export:** `uv run python scripts/export.py`.
