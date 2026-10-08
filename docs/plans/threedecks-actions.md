# Three Decks actions: plan

Status: 2026-10-08. Permission granted. Recon done. Reconciled with the hardened scraper (commits e9ec193 and 2f63489; see 6.0). Ready to execute.

**For:** a coding agent.
- Sections 1–4 are the design.
- Sections 5–8 are the work: Part A (shared foundation) and Part B (the actions crawler).
- Section 9 is the human operator's runbook.

The fleets crawler has its own plan, [threedecks-fleets.md](threedecks-fleets.md). The two are built and scraped **independently**: either can be done first, and neither needs the other.

This plan extends [threedecks-scraper.md](threedecks-scraper.md) ("the ship plan"). Its rules (2.3), politeness settings (4.2), resume design (4.3) and test layers (6) all apply.

## 1. Scope

### 1.1 What the `actions` crawler collects

- **The action index** (`index.php?display_type=select_action`): 1,089 actions, 50 per page, 22 pages.
- **Every action page** (`index.php?display_type=show_battle&id={id}`). Each gives:
  - the date or date range, and the war
  - the place, as `show_shipyard` place IDs
  - **coordinates**, when the page has a map
  - each side with its nations and commander, and each division
  - every participating ship with its commander and its losses or fate ("37 Killed, 47 Wounded Captured")
  - notes and cited sources

For the Spanish-losses map, an action supplies the place, the coordinates and the opposing forces behind a loss. The output joins to ship records through `td_id`, and ship history already links battles (`HistoryEvent.battle_ids`).

### 1.2 A separate crawler

- **Its own spider** (`actions`), its own runs, its own frontier kinds (`action_index`, `action`), its own tables (`action_index`, `actions`), its own exports and its own QA section.
- **It requests only two page types:** action index pages (POST `select_action`) and action pages (GET `show_battle`). It **never** requests ship, fleet, fleet-list, place, war, crewman or source pages. Participant ships, places, wars, commanders and the previous/next actions are stored as IDs only. Previous/next actions aren't followed either, because the index lists every action.
- **It has nothing to do with fleets.** It doesn't import, read or write anything that belongs to the fleets crawler.
- **What it shares with the ship crawler:** the settings, the HTTP cache file, the state file (separate tables), the base spider, and the `scripts/crawl.py` driver, which holds the crawl lock. It reads stored ship records only to seed battle IDs from ship history; that costs no requests.
- **It never runs at the same time as any other crawl.** Rule 10 and the crawl lock enforce this. The lock lives in `scripts/crawl.py`, not in the spider, so live runs always go through `crawl.py` (section 9).

### 1.3 Out of scope

Place, war, crewman, class and source pages (kept as IDs); geocoding; building the loss-event table; and anything about fleets.

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

- `action_index.html` (GET, page 1) and `action_index_p2.html` (POST, page 2)
- `action_157.html` (Trafalgar), `action_149.html` (2nd Cape St Vincent), `action_532.html` (Phoenix vs Didon, a single-ship action) and `action_988.html` (Siege of Le Havre)
- `action_notfound_probe.html` (id 999999)

They weigh 22 to 81 KB.

### 3.1 Action index (`select_action`)

- **Request.**
  - A plain GET returns page 1 of the **unfiltered** list. The real interface is the POST form `#action_selector`. Its HTML declares `multipart/form-data`, but a urlencoded POST works.
  - Fields: `formid=action_selector`, `page`, `limit=50`, `battle_name=""`, `type=0` (any), `war=0` (any), `date=""`, `date_yy=0000`, `date_mm=00`, `date_dd=00`.
  - The "Next" button only sets `page` and resubmits. A POST of page 2 returned "Showing Page 2 of 22".
- **Totals.** The table header reads "Action Search Results, 1,089 Records Found", and the text after the form reads "Showing Page N of 22". The list is ordered by date, starting at 1213.
- **Rows.** Each row is a `table#table_actions_list tr` with a `td.col_battle` cell:
  - `td.col_battle_dates`: one `span[@title]` in `D.M.YYYY` form, or two joined by " - " for a range.
  - `td.col_battle`: an `a[href*=show_battle]`.
  - `td.col_action_type`: plain text.
  - `td.col_war`: a `show_war` link plus years, but **possibly empty**.

  Page 1: 50 rows, 15 of them ranges, 8 with no war. The first row is id 1145, "Battle of Damme", 30.5.1213 - 31.5.1213, "Fleet action", war 112. Page 2 starts with 938, "Battle of Sluis", 26.5.1603.
- **Action types.** The `type` select lists 1 Fleet action, 2 Flotilla Action, 3 Single Ship Action, 4 Blockade, 5 Siege, 6 Landing operation, 7 Cutting out operation, 8 Convoy attack, 9 Encounter, 10 Bombardment. **The type appears only in the index,** never on the action page.

### 3.2 Action page (`show_battle&id=N`)

- **Title and name.** `<title>` holds "Name, date text"; `h1` holds the name.
- **Header.** The first `div` under `#datacol` that contains a `strong` element (its class varies: `column4 omega`, `column8`). Inside the `strong`:
  - **The date**, in long form: `21<sup>st</sup> October 1805`. A range reads `22nd May 1563 (1563/05/31 NS) - 31st July 1563 (1563/08/09 NS)`. The existing `parse_td_date` **cannot read this form.**
  - `Part of :` a `show_war` link plus years. Optional; the siege has none.
  - `Fought at :` `show_shipyard` links (the place, then its region). Optional.
  - `Previous action :` and `Next action :`, as `show_battle` links with date spans.
- **Coordinates.** When the page has `div#actionmapholder`, its script contains `position: new google.maps.LatLng(lat, lng)`, the marker. Use that line, not the commented-out `// public latlng = …` line above it. Battle 157 gives (36.29299, -6.25534) and battle 988 gives (49.49, 0.1). Battles 149 and 532 have no map.
- **`table#table_action_info`** is a flat sequence of `tr` elements, classified by shape:
  - **Spacer:** `<tr><th>&nbsp;</th></tr>`, and a trailing `<tr><td colspan="4">&nbsp;</td></tr>`.
  - **Side heading:** `th[colspan=4] > h2`. It holds the side label, one or more `show_nation` links ("Allied (Spain & Empire Français)") and an optional commander in a `div.tooltip`.
  - **Division heading:** `th[colspan=4] > span`, such as "Allied Rear, <commander>" or "English Vessels".
  - **Division note:** `tr.action_div_notes > td > p`.
  - **Column header:** `th` cells Ship Name / Commander / Notes.
  - **Participant:** three cells:
    - `td.column2`: a `show_ship` shiplink with the label "Neptuno (80)"
    - `td.column3`: a `show_crewman` link, or `&nbsp;`
    - `td.column3`: the notes, which may contain `<strong>Squadron Flagship</strong>`
- **Tooltips.** Each `div.tooltip` carries a `span.tooltiptext` (the ship's years and rate, or the crewman's nationality and service), and every participant cell starts with `span.hidden` ("Name : "). Both **must be excluded** from labels, names and notes.
- **Other sections:**
  - `div#table_page_notes`, "Notes on Action". Optional; may contain `h3` subheadings ("Killed.", "Wounded.").
  - `div#source_list`, in the same markup as ship pages.
  - The comments block ("Recent comments to other pages", `table#comment_list_table`) contains `show_ship` links and **must be ignored**.
- **Golden numbers:**

  | Action | Sides (nation IDs) | Divisions | Participants | War | Prev / next | Coordinates | Sources |
  |---|---|---|---|---|---|---|---|
  | 157 Trafalgar | [7, 4] and [1] | 8 | 73, all linked | 20 | 532 / 158 | 36.29299, -6.25534 | 2 |
  | 149 2nd Cape St Vincent | [7] and [1] | 6 | 55, all linked | 19 | 684 / 217 | none | 0 |
  | 532 Phoenix vs Didon | [1] and [4] | 0 | 2 | 20 | 199 / 157 | none | 2 |
  | 988 Siege of Le Havre | [1] | 1, with 1 division note | 5 | none | none | 49.49, 0.1 | 0 |

  More detail:
  - **157:** the first participant is Neptuno (`td_id` 2657) under commander 16313, with notes "37 Killed, 47 Wounded Captured". One participant is flagged "Squadron Flagship", and the page has Notes on Action.
  - **988:** fought at places [95, 1222]. Dates 1563-05-22 to 1563-07-31 (NS 1563-05-31 to 1563-08-09). The division label is "English Vessels".

### 3.3 Not-found and completeness

- **A missing action ID is a redirect.** `show_battle&id=999999` answers with a 302 to `index.php?display_type=select_action`. `_index.json` records the probe's `final_url` as `select_action`. Missing ships behave the same way: they redirect to the ship search, and `scripts/reparse.py:is_search_redirect` handles it. This has three consequences:
  - **In the spider,** Scrapy's `RedirectMiddleware` follows the 302. The callback receives the "Find an action" page, with `response.url` pointing at `select_action`. So the ID must come from `response.meta["key"]`, not from the URL (S4). The not-found check must run **before** anything else, because that page also holds 50 index rows.
  - **In the cache,** the HTTP cache sits outside the redirect middleware, so it stores the 302 itself under the `show_battle` request. `reparse.py` must treat a cached 3xx from a `show_battle` URL whose `Location` contains `display_type=select_action` as `not_found`.
  - **The followed GET of `select_action`** is cached once, and every later missing ID replays it. It is a GET, so its fingerprint never collides with the index POSTs.
- **Every real page ends with `span#copywrite_message` and `</html>`.** A response without the footer is incomplete: `is_action_page` must require `common.has_footer` (S2), as `is_ship_page` does.

### 3.4 Data-quality signals (keep raw; never reconcile in the scraper)

- **Participant lists are incomplete.** Battle 149 lists ship 2682 but not San José (112), which was captured at that action (ship plan 3.4). QA reports ship-history ↔ participant asymmetry.
- **Places are `show_shipyard` records** ("Le Havre", 95). Coordinates exist only where the page has a map.
- **Fate words in the notes** ("Captured") are free text. Keep the raw notes and the `<strong>` flags; classifying them is downstream work.
- **The index may be incomplete**, as the captures list was. Ship-history seeding plus the QA comparison measures this.

## 4. Design

### 4.1 Items (in `items.py`)

```python
@dataclass
class ActionIndexRow:
    battle_id: int | None
    name: str
    date: TDDate | None; end_date: TDDate | None     # from the D.M.YYYY spans + tooltips
    action_type: str | None                           # only the index carries the type
    war_id: int | None; war_text: str | None
    cells: list[str]                                  # lossless row text
    page: int

@dataclass
class ActionIndexPage:
    rows: list[ActionIndexRow]
    page: int | None; pages: int | None; total: int | None

@dataclass
class ActionSide:
    label: str                                        # h2 visible text (no hover cards)
    nation_ids: list[int]
    commander_ids: list[int]
    links: list[LinkRef]                              # every visible link, hover-card lines in LinkRef.tooltip

@dataclass
class ActionDivision:
    side_index: int | None
    label: str                                        # "Allied Rear, ..." visible text
    commander_ids: list[int]
    notes: list[str]                                  # tr.action_div_notes paragraphs
    links: list[LinkRef]

@dataclass
class Participant:
    side_index: int | None
    division_index: int | None
    td_id: int | None                                 # None when the row names a ship without a link
    ship_label: str                                   # "Neptuno (80)"
    ship: LinkRef | None                              # tooltip: ["1795-1805", "Spanish 80 Gun", "3rd Rate Ship of the Line"]
    commander_ids: list[int]; commander_text: str | None
    commanders: list[LinkRef]                         # tooltip: nationality, role, service years
    notes: str                                        # raw notes cell text
    flags: list[str]                                  # <strong> texts in notes ("Squadron Flagship")

@dataclass
class ActionRecord:
    battle_id: int
    name: str
    header_text: str                                  # lossless header text
    date: TDDate | None; end_date: TDDate | None      # parse_long_date on the header
    war_id: int | None; war_text: str | None
    places: list[LinkRef]                             # "Fought at" show_shipyard links
    previous_battle_id: int | None; next_battle_id: int | None
    latitude: float | None; longitude: float | None   # map marker only; never geocoded here
    sides: list[ActionSide]; divisions: list[ActionDivision]; participants: list[Participant]
    notes: str | None
    sources: list[SourceRef]
    unknown_rows: list[str]                           # table rows matching no known shape
    unknown_sections: list[str]
    url: str; fetched_at: str; content_sha256: str; parser_version: str
```

These follow ship parser v4's convention: visible text never contains hover-card text, and the hover card's lines survive in `LinkRef.tooltip` (`common.links`). Link IDs are always taken with `common.link_ids(node, kind)`, which matches the kind exactly; a substring test would count `show_shipyard` links as ships.

### 4.2 State (additive)

```sql
CREATE TABLE IF NOT EXISTS actions      (battle_id INTEGER PRIMARY KEY, record_json TEXT NOT NULL,
                                         parser_version TEXT, content_sha256 TEXT, fetched_at TEXT);
CREATE TABLE IF NOT EXISTS action_index (battle_id INTEGER PRIMARY KEY, row_json TEXT NOT NULL);
```

The frontier rows live in Part A's `page_frontier`, under kind `action_index` (key = page number) and kind `action` (key = battle ID).

- `save_action(record)` upserts the record and marks (`action`, id) `done` in **one** transaction.
- `save_action_index_page(page_key, rows)` upserts the page's rows and marks (`action_index`, page) `done` in **one** transaction. An interrupted index sweep therefore resumes page by page.

### 4.3 Spider flow

1. **The run** is `scripts/crawl.py --tiers <spider>`, which holds the crawl lock, watches the heartbeat and keeps the PC awake (6.0, S1). The spider itself takes no lock.
2. **Seed from ship history:** every `battle_id` already in stored ship records becomes an `action` row with `discovered_by='ship_history'`. This costs no requests.
3. **Seed index page 1.** Then yield every pending index page as a POST, at priority 10, so the index goes first. Then stream the pending actions in ascending ID order.
4. **Index page callback:**
   - Run the completeness check.
   - Parse, then save the rows and mark the page `done` together.
   - Seed pages 2 to N from "Showing Page 1 of N", and request only the **newly inserted** ones.
   - Seed the row IDs (`discovered_by='action_index'`), and request only the newly inserted ones.
5. **Action page callback:** the shared `parse_entity_page` with the `ACTION` kind yields an `ActionRecord`, which the pipeline stores with `save_action`.

A rerun after the ship crawl's Tier C fetches only the battle IDs that Tier C newly cites. Everything else is `done`, or replays from the cache.

**Ship-history seeding reads the local `state.sqlite`.** Run the actions crawl on the machine that holds the ship crawl's state, so the seeds are there. On a machine with no ship records, only the index seeds it. That is still the full 1,089, but the QA comparison of the index against ship history then has nothing to compare.

Errors, network outages, incomplete-page streaks, cool-offs and blocks behave exactly as for ships, because they come from the shared base (S4) and the unchanged middleware.

### 4.4 Size and order

The delay is 6 s with ±1 s jitter, plus about 1.5 s per response: roughly 480 pages per hour. The index POSTs are slower, at about 45 KB each.

| Run | Requests | Time |
|---|---|---|
| D-smoke | index page 1 + 24 action pages (`-s CLOSESPIDER_PAGECOUNT=25`) | ~3–4 min |
| Tier D | 22 index POSTs + 1,089 action pages (+ any extra IDs from ship history) | ~2.3 h |
| D-gap (optional, later) | IDs below the maximum that neither the index nor ship history mention | depends; decide from QA |

The agreed run order is: ship smoke test → Tier A → **actions** → fleets → Tier C. The crawl lock prevents any overlap.

## 5. Before you start

### 5.1 Read first

- **This plan:** all of it. Section 3 is the markup reference for every parser task.
- **The ship plan:** 2.3, 4.2, 4.3 and 6.
- **Code:**
  - `scrapers/threedecks/threedecks/`: `settings.py`, `politeness.py`, `middlewares.py`, `cache.py`, `lock.py`, `extensions.py`, `state.py`, `items.py`, `pipelines.py`, `spiders/base.py`, `spiders/captures.py`, `spiders/ships_all.py`, `parsing/ship_page.py`, `parsing/grid.py`, `parsing/dates.py`
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
   - Don't create, import or modify anything fleet-specific: `parsing/fleets.py`, `spiders/fleets.py`, fleet items, fleet tables.
   - Shared files (`items.py`, `state.py`, `pipelines.py`, `resume_harness.py`, the scripts) only gain **additions**. Never restructure code the fleets plan may also add to.
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
- **Git:** work on branch `data-layout`. Commit after each task: `Three Decks S<n>: <title>` for Part A, `Three Decks actions A<n>: <title>` for Part B. Never push.

### 5.4 Baseline and Task 0

- **Before Part A** (measured 2026-10-08, after merge 2f63489): `uv run pytest -q` gives **488 passed, 2 failed, 2 skipped, 68 deselected** (deselected = network-marked), and `uv run ruff check` is clean.
- **The 2 failures are known and unrelated:** `tests/shiplosses/test_extractors.py::test_golden_extractor_outputs` and `tests/shiplosses/test_extractors_phase4.py::test_golden_counts_phase4` need raw UKHO and INFOMAR files under `data/raw/` that aren't on every machine. Everywhere this plan says "green", it means: no new failures, and those two may fail only for that reason.
- **If Part A is already done**, because the fleets plan ran first: there are more tests, and all of them must pass.

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

## 7. Part B: the actions crawler (tasks A1–A9)

Each task lists its files, the tests to write first, implementation notes, and its exit criterion ("Done when").

### Task A1: Long-form dates

`parse_td_date` handles `D.M.YYYY`, `YYYY/MM/DD` and the qualifiers `bef.`, `aft.` and `c.`. It doesn't handle the written-out dates in action headers.

- **Files:** `parsing/dates.py`, `tests/test_dates.py`.
- **New function `parse_long_date(text) -> tuple[TDDate | None, TDDate | None]`:**
  - Normalise whitespace, then split on ` - ` **outside parentheses** into a start part and an optional end part.
  - In each part, a trailing `(YYYY/MM/DD NS)` sets `gregorian_iso`.
  - The main text matches one of three forms:
    - `(\d{1,2})\s*(st|nd|rd|th)?\s+(of\s+)?<Month>\s+(\d{4})` → day precision
    - `<Month>\s+(\d{4})` → month precision
    - `(\d{4})` → year precision
  - A leading weekday is ignored. `raw` is the part's text. An unparseable part gives `TDDate(raw=part)` with precision None. Empty text gives `(None, None)`.
  - Reuse `_MONTHS`.
  - The header renders `21<sup>st</sup>`, so `"21 st October 1805"` (a space before the suffix) must parse.
- **Tests (parametrised):**

  | Input | Expected |
  |---|---|
  | `21st October 1805`, `21 st October 1805` | 1805-10-21, day |
  | `14th February 1797` | 1797-02-14, day |
  | `22nd May 1563 (1563/05/31 NS) - 31st July 1563 (1563/08/09 NS)` | start 1563-05-22 (gregorian 1563-05-31), end 1563-07-31 (gregorian 1563-08-09) |
  | `May 1576` | 1576-05, month |
  | `1801` | 1801, year |
  | `Tuesday 14th of August 1798` | 1798-08-14, day |
  | `""` | `(None, None)` |
  | `sometime` | `(TDDate(raw="sometime"), None)` |

- **Done when:** green; the existing date tests are unchanged.

### Task A2: Action items

- **Files:** `items.py` (additions only), `tests/test_items_actions.py` (new).
- Add the section 4.1 dataclasses: `ActionIndexRow`, `ActionIndexPage`, `ActionSide`, `ActionDivision`, `Participant` and `ActionRecord`. Reuse the existing `LinkRef` (with its `tooltip` field), `TDDate` and `SourceRef`.
- **Test:** each type survives a round trip through `dataclasses.asdict` and `json.dumps`.
- **Done when:** green.

### Task A3: Action parsers

- **Files:** `parsing/actions.py` (new), `tests/test_actions.py` (new). New synthetic fixtures: `tests/fixtures/synthetic/action_full.html`, `action_minimal.html`, `action_index.html` and `action_notfound.html`.
- **Use the S2 helpers only:** `common.visible_text`, `common.links`, `common.link_ids`, `common.parse_sources` and `common.has_footer`. Don't write new text or link extraction.
- **API:**

  ```python
  ACTION_PARSER_VERSION = "1"
  def is_action_page(sel) -> bool          # table#table_action_info, a non-empty h1, and common.has_footer
  def is_action_not_found(sel) -> bool     # not is_action_page and <title> starts "Find an action" (case-insensitive)
  def is_action_index_page(sel) -> bool    # table#table_actions_list and common.has_footer
  def parse_action_index(sel) -> ActionIndexPage
  def parse_action(sel, url, *, fetched_at="", content_sha256="", parser_version=ACTION_PARSER_VERSION) -> ActionRecord
  ```

- **Index:**
  - The rows are `table#table_actions_list tr` that have a `td.col_battle`.
  - Dates come from the `span[@title]` elements in `td.col_battle_dates`, through `parse_td_date(text, title)`. With two spans, the second is `end_date`.
  - `battle_id` is `link_ids(td.col_battle, "show_battle")[0]`, or None when the row has no battle link.
  - `action_type` is `td.col_action_type`. `war_id` and `war_text` come from `td.col_war`, which may be empty.
  - `cells` holds each `td`'s `visible_text`.
  - `total` comes from "N Records Found" (strip the commas); `page` and `pages` come from "Showing Page N of M".
- **Action page,** scoped to `div#datacol`:
  - **Header:** the first child `div` of `#datacol` that contains a `strong` element and precedes `table#table_action_info`.
    - `header_text` is its visible text.
    - The date is `parse_long_date` on the text before the first `<br>`.
    - Labelled lines: `Part of :` gives `war_id`/`war_text`; `Fought at :` gives `places` (`common.links` filtered to kind `show_shipyard`); `Previous action :` and `Next action :` give their `show_battle` IDs.
  - **Coordinates:** apply `position:\s*new google\.maps\.LatLng\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)` to the script text inside `div#actionmapholder`. Without a map, both values are None.
  - **`table#table_action_info`:** iterate its `tr` elements in order and classify each one:
    - **Side heading** (`th/h2`): a new `ActionSide`.
      - `label` is `visible_text`; `links` is `common.links`.
      - `nation_ids` and `commander_ids` come from `link_ids(…, "show_nation")` and `link_ids(…, "show_crewman")`.
      - Reset the current division.
    - **Division heading** (`th[@colspan]/span`): a new `ActionDivision`, with `side_index` set to the current side.
    - **Division note** (`tr.action_div_notes`): append to the current division's notes. With no division, append to `unknown_rows`.
    - **Participant** (has `td[contains(@class,'column2')]`):
      - `ship` is the first `common.links` entry of kind `show_ship` in that cell. `td_id` and `ship_label` are its `id` and `text`. Without one, `td_id` and `ship` are None, and the label is the cell's `visible_text(drop_hidden=True)`.
      - The commander comes from the 2nd `td`: `commanders` is its `show_crewman` links, `commander_ids` their IDs, and `commander_text` its `visible_text` (None when blank).
      - `notes` is the 3rd `td`'s `visible_text`; `flags` holds its `strong` texts.
    - **Column header** (contains "Ship Name") or **spacer** (only whitespace or nbsp): skip.
    - **Anything else:** `unknown_rows.append(norm(text)[:200])`.
  - **`notes`:** the visible text of `div#table_page_notes` minus its `h2`, or None.
  - **`sources`:** `common.parse_sources`.
  - **`unknown_sections`:** every `h2` in `#datacol` outside `table#table_action_info` other than "Notes on Action", "Sources" and "Recent comments to other pages". Never read `table#comment_list_table`.
  - **`battle_id`:** `extract_id(url)`. The spider passes the request URL, not a redirect target.
- **Synthetic fixtures,** each quirk from 3.2 once, plus the footer `<span id="copywrite_message">Copyright</span>` on every page:
  - **`action_full.html`:**
    - a header with a range, "Part of", "Fought at" with 2 links, and Previous/Next
    - a map script with the commented line plus the `position:` line
    - side 1 with two nations and a tooltip commander; two divisions (one with a commander) and one division note
    - participants: one with a flag and notes, one with nbsp as commander, one with no ship link, one whose cell also contains a `show_shipyard` link (it must not become `td_id`)
    - side 2 with one division
    - one unknown row (`<tr><td colspan="2">odd</td></tr>`)
    - Notes on Action, a source list and an unknown `h2` section
    - a comment table containing `show_ship` links
  - **`action_minimal.html`:** one side, no divisions, no map, no notes, no war.
  - **`action_index.html`:** 3 rows (a range with a war, a single date with an empty war cell, and a row without a battle link), plus "N Records Found" and "Showing Page 1 of 2".
  - **`action_notfound.html`:** title "Find an action", the index table, no `table_action_info`. It's what the spider sees after the 302.
  - **`action_truncated.html`:** `action_minimal.html` without the footer, so `is_action_page` is False.
- **Golden tests** (`real_pages`), from section 3:
  - **157:**
    - name "Battle of Trafalgar"; date 1805-10-21; war 20; previous 532, next 158; (36.29299, -6.25534)
    - sides [7, 4] and [1]; 8 divisions; 73 participants, all with `td_id`; 2682 among them
    - the first participant: `td_id` 2657, label "Neptuno (80)", `ship.tooltip == ["1795-1805", "Spanish 80 Gun", "3rd Rate Ship of the Line"]`, commander 16313 whose `tooltip[0] == "Spanish"`, notes "37 Killed, 47 Wounded Captured"
    - one participant flagged "Squadron Flagship"; 2 sources; notes not None
  - **149:** 55 participants; 2682 among them and **112 not**; sides [7] and [1]; 6 divisions; war 19; 684/217; no coordinates; 0 sources.
  - **532:** 2 participants; sides [1] and [4]; 0 divisions; war 20; 199/157.
  - **988:** start 1563-05-22 (gregorian 1563-05-31) and end 1563-07-31 (gregorian 1563-08-09); places [95, 1222]; no war; 1 side [1]; 1 division "English Vessels" with 1 note; 5 participants; (49.49, 0.1).
  - **Across all four:**
    - `unknown_rows == []` and `unknown_sections == []`
    - no **visible** text field (`label`, `ship_label`, `commander_text`, `notes`) contains "Naval Sailor". That text belongs in `LinkRef.tooltip`, never in visible text.
    - every `is_action_page` is True
  - **`action_notfound_probe`:** `is_action_not_found` is True and `is_action_page` is False.
  - **`action_index`:** 50 rows; total 1089; page 1 of 22; the first row is 1145, "Battle of Damme", 1213-05-30 to 1213-05-31, "Fleet action", war 112; 15 rows have an `end_date`; 8 have no war.
  - **`action_index_p2`:** page 2 of 22; the first row is 938, "Battle of Sluis", 1603-05-26.
  - **Cross-check:** parse `ship_2682.html` with `parse_ship`. For each `history[].battle_ids` value that has a fixture (149, 157), 2682 is a participant.
- **Done when:** green.

### Task A4: Action state

- **Files:** `state.py` (additions only), `tests/test_state_actions.py` (new).
- **Schema:** add the section 4.2 DDL to `_SCHEMA`.
- **Methods:**

  ```python
  save_action(record: ActionRecord) -> None                       # upsert + _page_done_sql('action', str(id)), one transaction
  save_action_index_page(page_key: str, rows: list[ActionIndexRow]) -> int   # upsert rows with an id + page done; returns rows stored
  get_action(battle_id) -> dict | None
  iter_actions(); iter_action_index(); action_count() -> int
  history_battle_ids() -> list[int]                               # sorted unique battle ids across ships' history
  ```

- **Tests first:**
  - `save_action` writes the record and `done` together. Mirror `test_done_and_record_are_written_together`.
  - `save_action_index_page` skips rows without an ID and marks the page `done`.
  - Ship 157 and action 157 don't interfere.
  - `history_battle_ids` returns the IDs from saved ship records.
  - Reopening keeps everything.
- **Done when:** green.

### Task A5: `ACTION` kind and pipeline

- **Files:** `parsing/actions.py` or a new `threedecks/kinds_actions.py`, `pipelines.py` (additions only), `tests/test_pipelines.py`.
- **The kind:** `ACTION = register(PageKind("action", "show_battle", is_action_page, is_action_not_found, parse_action, ACTION_PARSER_VERSION))`. Make sure it's registered whenever the spiders module loads.
- **Validation:** drop an `ActionRecord` without a `battle_id` or a `name`.
- **Storage:** `StatePipeline` routes `ActionRecord` to `save_action`.
- **Index rows are not items.** The spider stores them with `save_action_index_page`, so a page's rows and its `done` mark stay atomic.
- **Tests:** mirror the ship pipeline tests.
- **Done when:** green.

### Task A6: The `actions` spider

- **Files:** `threedecks/forms.py` (new), `spiders/actions.py` (new), `scripts/fetch_fixtures.py` (import the form from `threedecks.forms`), `tests/test_spiders_actions.py` (new).
- **`forms.py`:** `action_index_form(page: int) -> dict`, moved unchanged out of `fetch_fixtures.py`.
- **Spider:**

  ```python
  class ActionsSpider(TDSpider):
      name = "actions"
      default_max_depth = 0
      def start_requests(self):
          self.store.seed_pages("action", [str(i) for i in self.store.history_battle_ids()],
                                discovered_by="ship_history")
          self.store.seed_pages("action_index", ["1"], discovered_by="start")
          for key in self.store.pending_pages("action_index", self.max_attempts):
              yield self.index_request(int(key))                  # priority=10
          yield from self.stream_pending_pages("action")
      def index_request(self, page): ...   # FormRequest POST {base}/index.php?display_type=select_action,
                                           # formdata=action_index_form(page), meta kind='action_index', key=str(page),
                                           # errback=self.on_entity_error, dont_filter=True, priority=10
      def parse_index(self, response): ...
  ```

- **`parse_index`:**
  1. **Completeness:** `is_action_index_page` (which includes the footer). If it fails, take the base's incomplete path (S4): drop the cache entry, mark `error`, retry once, and count towards the incomplete streak.
  2. **Parse** in try/except, recording `parse_error` (`threedecks/action_index/parse_error`).
  3. **Store:** `save_action_index_page(key, rows)`.
  4. **More index pages:** `seed_pages("action_index", 2..pages)`. Yield `index_request` for **newly inserted** keys only.
  5. **Actions:** `seed_pages("action", ids, discovered_by="action_index")`. Yield `entity_requests("action", new_ids)` for newly inserted keys only.
  6. **Stats:** `threedecks/action_index/rows` and `threedecks/action_index/row_without_id`.
- **Action pages** go through `parse_entity_page` with the `ACTION` kind. The key comes from meta, so a missing ID whose 302 Scrapy followed to the "Find an action" page is recorded as (`action`, id) `not_found`.
- **Tests first:**
  - On an empty store, `start_requests` yields exactly one POST, whose form data equals `action_index_form(1)`.
  - **History seeding:** save a ship whose history has `battle_ids [149, 157]`. `start_requests` yields the index request, then action requests for 149 and 157.
  - **`parse_index` on synthetic `action_index.html`:** the rows are stored, page 1 is `done`, page 2 is seeded and requested once, and each linked action is requested once. A second call on the same response yields no requests.
  - **Redirected not-found:** an `HtmlResponse` of `action_notfound.html` with `url=…display_type=select_action` and request meta `{kind: "action", key: "999999"}` → (`action`, "999999") is `not_found`, nothing is yielded, and it isn't parsed as an index.
  - **Truncated:** `action_truncated.html` → `error`, one retry, `threedecks/action/incomplete_page`.
  - **Separation:** collect every request from `start_requests`, `parse_index` and `parse_entity_page` over all the synthetic action fixtures. For each one, `parse_qs(urlparse(url).query)["display_type"]` is exactly `["select_action"]` or `["show_battle"]`. Compare exactly, not by substring: `show_ship` is a prefix of `show_shipyard`.
  - `ActionsSpider` defines no `custom_settings`.
- **Done when:** green.

### Task A7: Resume and lock tests

- **Files:** `tests/resume_harness.py` (an `add_action_routes(site, action_ids)` helper, additions only), `tests/test_resume_actions.py` (new).
- **The routes:**
  - **POST `select_action`:** read `page` and `limit` from the urlencoded body. Serve a minimal index page in the 3.1 markup, with "N Records Found", "Showing Page p of P", rows and the footer.
  - **GET `show_battle`:** for a known ID, a minimal action page with `h1`, `table#table_action_info`, one side, one participant and the footer. For an unknown ID, a **302** with `Location: /index.php?display_type=select_action`, as the real site does.
  - **GET `select_action`:** the "Find an action" page with the footer.
- **The harness** already sets `THREEDECKS_MAX_COOLOFFS=0`, so a 429 closes `blocked` at once, as in `test_resume.py`.
- **Tests** (mirror `tests/test_resume.py`):
  - **Graceful stop:** 120 actions (3 index pages) plus 2 unknown IDs seeded from ship history.
    - The first run stops with `CLOSESPIDER_ITEMCOUNT=40`, and a rerun completes.
    - Every known action is `done` once, and both unknown IDs are `not_found`.
    - The server saw each action and each index page once, and the export has 120 unique actions.
  - **Hard kill:** `proc.kill()` after 40 items, then a rerun. At most one action is fetched twice.
  - **Truncated cache entry:** plant a footer-less body for one action in `httpcache.sqlite`. The rerun refetches it, and the record is complete.
  - **Interrupted index sweep:** a 429 on index page 2 closes the run as `blocked`, with page 1 `done`. After the block clears, a rerun fetches pages 2 and 3, and never page 1 again.
  - **Cool-off:** one 429 on an action page with `-s THREEDECKS_MAX_COOLOFFS=2 -s THREEDECKS_COOLOFF_SECS=1`. The crawl pauses, retries the same request once, and completes. Mirror the existing ship cool-off test.
  - **Crawl lock (through `crawl.py`):** while the test holds `CrawlLock(data / "crawl.lock")`, run `python scripts/crawl.py --tiers actions --allow-sleep --pause-seconds 0 -s DOWNLOAD_DELAY=0 -s DOWNLOAD_DELAY_JITTER=0 -s AUTOTHROTTLE_ENABLED=False -s THREEDECKS_MAX_COOLOFFS=0` in a subprocess (protected overrides are allowed against a local site, see `politeness.refused_overrides`), with `THREEDECKS_BASE_URL` pointing at `FakeSite`, `THREEDECKS_DATA_DIR` at `data`, and `THREEDECKS_CONTACT` set. It exits 2, and the site saw **zero** requests. Release the lock, and the same command completes the crawl.
  - **Namespaces:** ship 157 and action 157 both exist. Run `ships_all`, then `actions`. Both are stored, and both frontier rows are `done`.
- **Done when:** green. Keep the new tests under about 2 minutes in total.

### Task A8: Driver, scripts and recipes

All changes are additions. Don't restructure what the ship code or the fleets plan has, or will have.

- **`scripts/crawl.py`:** append `"actions"` to `EXTRA_TIERS` (S1). `crawl_all.py` doesn't change.
- **`justfile`:** add two recipes:

  ```
  # Three Decks actions crawl (~2.3 h; separate from the ship tiers); rerun to resume, --rerun after Tier C
  threedecks-actions *args:
      uv run python scripts/crawl.py --tiers actions {{ args }}

  # Actions smoke test: 25 pages (~4 min)
  threedecks-actions-smoke *args:
      uv run python scripts/crawl.py --tiers actions -s CLOSESPIDER_PAGECOUNT=25 {{ args }}
  ```

- **`crawl_status.py`:** an "actions" block giving the `action_index` and `action` status counts, the actions stored, and the last `actions` run with its ETA.
- **`reparse.py`:**
  - If `--kind` doesn't exist yet, add it, with `ship` and `all` among the choices. Then add `action` and `action_index`.
  - Read the cache only through `load_cached_response`. The bodies are zstd-encoded.
  - `show_battle` URLs are reparsed with `parse_action`.
  - A cached 3xx whose `Location` contains `display_type=select_action` is `not_found`. Write `is_action_redirect` next to `is_search_redirect`.
  - A cached `select_action` POST response takes its page key from the parsed "Showing Page N", because every index POST has the same URL. The cached GET of `select_action`, the redirect target, is skipped: it isn't an index page of ours.
  - The not-found and completeness rules are the spider's. No network.
- **`export.py`:** adds four files.
  - `actions.jsonl` and `action_index.jsonl`.
  - `actions.parquet`, one row per action:
    - `battle_id` and `name`
    - `action_type`, joined from the index
    - `date_iso`, `date_gregorian`, `end_date_iso` and `end_date_gregorian`
    - `war_id`, and `place_ids` as a comma string
    - `latitude` and `longitude`
    - `previous_battle_id` and `next_battle_id`
    - `side_count` and `participant_count`
    - `url`, `fetched_at`, `content_sha256` and `parser_version`
  - `action_participants.parquet`: `battle_id`, `side_index`, `side_label`, `side_nation_ids`, `division_label`, `td_id`, `ship_label`, `ship_tooltip` (joined with " | "), `commander_ids`, `notes` and `flags`.
- **`qa_report.py`:** an "Actions" section, in both the Markdown and the JSON output. It counts:
  - index IDs not fetched, and fetched IDs missing from the index
  - battle IDs in ship history with no action record
  - asymmetry: a ship's history links battle X, but X doesn't list the ship, and the reverse
  - action dates that differ from the linked history-event date
  - participants with no `td_id`, and participants not found in `ships`
  - the share of actions with coordinates
  - `unknown_rows` and `unknown_sections`
  - frontier errors for the `action` and `action_index` kinds
- **Tests:**
  - **Export:** from a state DB holding two synthetic action records, the files exist, the row counts match, and every participant row has its `battle_id`.
  - **QA:** a prepared asymmetry (a ship's history cites battle 5, whose participants lack the ship) is reported.
  - **Reparse:** a cache DB written with `SqliteCacheStorage` holds one zstd-encoded action page and one 302 to `select_action`. Reparsing gives a stored record and a `not_found`. Mirror `tests/test_reparse.py`.
  - **Status:** the output contains the actions block.
  - **Driver:** `--tiers actions` is accepted, and the default tiers still exclude it.
- **Done when:** green.

### Task A9: Docs and final check

- **Ship plan, section 4 tree:** add `pages.py`, `forms.py`, `parsing/common.py`, `parsing/actions.py` and `spiders/actions.py`, unless they're already there.
- **Final check:** `uv run ruff check` clean, and `uv run pytest -q` green in the sense of 5.4. Then report back (section 8).

## 8. Report back

When finished, or when stopped by a rule in 5.2, report:

- one line per task (S1–S4, A1–A9): done / skipped (already done) / blocked, and its commit hash
- the final `pytest` summary line and the `ruff` result
- any deviation from this plan, with the reason
- any real-fixture number that disagreed with section 3
- open questions for the operator

## 9. Operator runbook (human only; not for the agent)

Run from the repo root, in a **new** terminal so the `THREEDECKS_CONTACT` user variable is visible. Run on the machine that holds the ship crawl's `data/threedecks/` (4.3).

- **Locking:** every command below goes through `scripts/crawl.py` or `scripts/smoke.py`, which hold the crawl lock. A second crawl refuses to start. Never run `scrapy crawl` by hand against the site.
- **Blocks:** a 429 or a challenge pauses the crawl for 15/30/60 min. A `blocked` close means stop and contact the owner (rule 5).

1. **Ship smoke test,** if the ship crawler hasn't run on this machine yet: `just threedecks-smoke`.
2. **Tier A,** if not done yet: `just threedecks-crawl` (it stops at its ship target; see the ship plan).
3. **Actions smoke test:** `just threedecks-actions-smoke`.
   - It ends with "page cap reached during actions".
   - The closing stats must show no `threedecks/action/parse_error`, `incomplete_page`, `unknown_row` or `unknown_section`.
   - Then run `just threedecks-actions`, press Ctrl+C after about 10 pages, and run it again. It must continue where it stopped.
4. **Tier D:** `just threedecks-actions` (about 2.3 h; keeps the PC awake; logs in `data/threedecks/logs/`). Then:
   - `uv run python scripts/crawl_status.py`
   - `uv run python scripts/qa_report.py --out data/threedecks/exports/qa.md`
   - Decide on D-gap from the "fetched IDs missing from the index" count.
5. **After the ship crawl's Tier C:** `just threedecks-actions --rerun`. It fetches only the newly cited battle IDs; everything else is `done` or replays from the cache.
6. **Export:** `uv run python scripts/export.py`.
