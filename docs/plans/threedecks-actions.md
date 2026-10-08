# Three Decks actions: plan

Status: 2026-10-08. Permission granted. Recon done. Ready to execute.

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
- **What it shares with the ship crawler:** the settings, the HTTP cache file, the state file (separate tables), the crawl lock and the base spider. It reads stored ship records only to seed battle IDs from ship history; that costs no requests.
- **It never runs at the same time as any other crawl.** Rule 10 and the crawl lock enforce this.

### 1.3 Out of scope

Place, war, crewman, class and source pages (kept as IDs); geocoding; building the loss-event table; and anything about fleets.

## 2. Permission and rules

The owner (Cy Harrison) granted actions and fleet lists on 2026-10-08, at the same 5 s rate, with no other conditions. The record is in ship plan 2.1, and the request text is in ship plan Appendix B. **Place pages are not permitted.**

Ship-plan rules 1–10 apply, notably:
- one request every 5 s, one at a time
- stop on 403, 429 or a challenge; never evade
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

- **A missing action ID** (`id=999999`) returns the action index page itself. The title is "Find an action", and there's no `table#table_action_info`. The not-found check must run **before** anything else, because that page also holds 50 index rows.
- **Every real page ends with `span#copywrite_message` and `</html>`.** A response without the footer is incomplete (Part A, S3).

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
    label: str                                        # h2 text without tooltips
    nation_ids: list[int]
    commander_ids: list[int]

@dataclass
class ActionDivision:
    side_index: int | None
    label: str                                        # "Allied Rear, ..." without tooltips
    commander_ids: list[int]
    notes: list[str]                                  # tr.action_div_notes paragraphs

@dataclass
class Participant:
    side_index: int | None
    division_index: int | None
    td_id: int | None                                 # None when the row names a ship without a link
    ship_label: str                                   # "Neptuno (80)"
    commander_ids: list[int]; commander_text: str | None
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

1. **`start()`** takes the crawl lock (S2).
2. **Seed from ship history:** every `battle_id` already in stored ship records becomes an `action` row with `discovered_by='ship_history'`. This costs no requests.
3. **Seed index page 1.** Then yield every pending index page as a POST, at priority 10, so the index goes first. Then stream the pending actions in ascending ID order.
4. **Index page callback:**
   - Run the completeness check.
   - Parse, then save the rows and mark the page `done` together.
   - Seed pages 2 to N from "Showing Page 1 of N", and request only the **newly inserted** ones.
   - Seed the row IDs (`discovered_by='action_index'`), and request only the newly inserted ones.
5. **Action page callback:** the shared `parse_entity_page` with the `ACTION` kind yields an `ActionRecord`, which the pipeline stores with `save_action`.

A rerun after the ship crawl's Tier C fetches only the battle IDs that Tier C newly cites. Everything else is `done`, or replays from the cache.

### 4.4 Size and order

At about 540 pages per hour (ship plan 5):

| Run | Requests | Time |
|---|---|---|
| D-smoke | index page 1 + 24 action pages (`-s CLOSESPIDER_PAGECOUNT=25`) | ~3 min |
| Tier D | 22 index POSTs + 1,089 action pages (+ any extra IDs from ship history) | ~2.1 h |
| D-gap (optional, later) | IDs below the maximum that neither the index nor ship history mention | depends; decide from QA |

The agreed run order is: ship smoke test → Tier A → **actions** → fleets → Tier C. The crawl lock prevents any overlap.

## 5. Before you start

### 5.1 Read first

- **This plan:** all of it. Section 3 is the markup reference for every parser task.
- **The ship plan:** 2.3, 4.2, 4.3 and 6.
- **Code:**
  - `scrapers/threedecks/threedecks/`: `settings.py`, `middlewares.py`, `cache.py`, `state.py`, `items.py`, `pipelines.py`, `spiders/base.py`, `spiders/captures.py`, `spiders/ships_all.py`, `parsing/ship_page.py`, `parsing/grid.py`, `parsing/dates.py`
  - `scripts/`: every file
  - `tests/`: `test_spiders.py`, `test_state.py`, `test_middleware.py`, `test_resume.py`, `resume_harness.py`

### 5.2 Hard rules

1. **No network.** Never crawl threedecks.org, never run `scripts/fetch_fixtures.py`, and never fetch a Three Decks URL by any means. Every test runs offline, against fixtures or against `FakeSite` on 127.0.0.1. Live runs belong to the operator (section 9).
2. **Never loosen politeness.**
   - Don't change `DOWNLOAD_DELAY`, `RANDOMIZE_DOWNLOAD_DELAY`, `CONCURRENT_REQUESTS*`, `AUTOTHROTTLE_*`, `ROBOTSTXT_OBEY`, `RETRY_HTTP_CODES`, `HTTPCACHE_*` or `USER_AGENT`.
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
8. **Ship behaviour stays identical**, except where S1 and S3 say otherwise. An existing test may change only where a task lists the change.
9. **Stop and report rather than guess** if any of these happens:
   - a real fixture contradicts a number in section 3
   - an existing test needs an unlisted change
   - anything seems to need the network
   - the baseline doesn't match

### 5.3 Environment

- **Platform:** Windows 11, with Git Bash and PowerShell. Python ≥ 3.11 through `uv`.
- **Commands,** from the repo root: `uv run pytest -q`, `uv run pytest -q tests/test_x.py -k name` and `uv run ruff check`.
- **Scrapy:** the project lives in `scrapers/threedecks/`. The resume harness runs `python -m scrapy crawl <spider>` from there.
- **Real fixtures:** in `tests/fixtures/real/`, with `_index.json`. `real_pages` tests skip themselves when the directory is absent.
- **Spider unit tests** build spiders without a crawler (`make()` in `tests/test_spiders.py`). Code that touches `self.crawler`, `self.settings` or stats must tolerate their absence. For stats tests, use `scrapy.utils.test.get_crawler`.
- **Git:** work on branch `data-layout`. Commit after each task: `Three Decks S<n>: <title>` for Part A, `Three Decks actions A<n>: <title>` for Part B. Never push.

### 5.4 Baseline and Task 0

- **Before Part A** (measured 2026-10-08): `uv run pytest -q` gives **177 passed, 54 deselected** (the deselected tests are network-marked), and `uv run ruff check` is clean.
- **If Part A is already done**, because the fleets plan ran first: there are more tests, and all of them must pass.

**Task 0.** Run the baseline. If `git status` shows uncommitted plan work under `docs/plans/` or in `scripts/fetch_fixtures.py`, commit it as `Three Decks: actions and fleets plans, recon fixture list`.

## 6. Part A: shared foundation (tasks S1–S6)

**This part is identical in the actions plan and the fleets plan.** Whichever plan is executed first does it; the other one skips it.

**Skip check:** Part A is done if `git log --oneline` shows the six commits "Three Decks S1:" through "Three Decks S6:", and `uv run pytest -q` is fully green. If so, go straight to Part B. If only some S-commits exist, continue from the first one missing.

Part A also fixes ship-crawler bugs. Until S1 lands, no crawl of any kind can run live.

### Task S1: Fix the Cloudflare false positive (urgent)

**The bug.** Every Three Decks page, ship pages included, embeds Cloudflare's passive bot-detection script `/cdn-cgi/challenge-platform/scripts/jsd/main.js`. `BlockDetectionMiddleware.CHALLENGE_MARKERS` contains `b"challenge-platform"`. On the real `ship_2682.html` with status 200, the middleware called `close_spider(spider, "blocked")`. So **every crawl, the ship crawl included, stops on its first real page.**

The existing tests pass only because they use synthetic bodies. Verified on 2026-10-08: all 18 real fixtures contain the beacon, and none contains `cf-chl`, `_cf_chl_opt` or a "Just a moment" title.

- **Files:** `threedecks/middlewares.py`, `tests/test_middleware.py`.
- **Tests first:**
  - `test_real_pages_are_not_challenges`: `@pytest.mark.real_pages`, parametrised over every `tests/fixtures/real/*.html`. Each page at status 200 → `close_spider` not called.
  - `test_passive_beacon_is_not_a_challenge`: a synthetic body containing `<script>…/cdn-cgi/challenge-platform/scripts/jsd/main.js…</script>` → not closed.
  - `test_just_a_moment_title_closes_spider`: `<title>Just a moment...</title>`, at status 200 and at status 403 → closed with `blocked`.
  - `test_cf_chl_opt_closes_spider`: a body containing `window._cf_chl_opt` → closed.
  - The existing 403 and 429 tests stay as they are.
- **Implementation:**
  - Remove `b"challenge-platform"`.
  - A response is a challenge if its `<title>` element contains "just a moment" (case-insensitive; never match body text, because comments are user content), or if its body contains `_cf_chl_opt` or `cf-chl`.
- **Done when:** green, with all 18 real pages passing.

### Task S2: Crawl lock (rule 10: one crawler at a time)

Scrapy's `DOWNLOAD_DELAY` applies per process. Two spiders running together would send two requests every 5 s and break the owner's condition.

- **Files:** `threedecks/lock.py` (new), `spiders/base.py`, `scripts/fetch_fixtures.py`, `tests/test_lock.py` (new).
- **API:**

  ```python
  class LockHeld(Exception): ...             # carries holder: dict | None
  class CrawlLock:
      def __init__(self, path: Path, owner: str): ...
      def acquire(self) -> bool: ...          # non-blocking; True if acquired
      def release(self) -> None: ...
      def holder(self) -> dict | None: ...    # contents of <path>.json, if readable
      # context manager: __enter__ raises LockHeld if it can't acquire
  ```

  - Open `data_dir/crawl.lock` in `a+` mode and seek to 0.
  - On Windows, call `msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)`; on POSIX, call `fcntl.flock(fd, LOCK_EX | LOCK_NB)`.
  - Keep the handle open while the lock is held; the OS releases it if the process dies, so stale locks can't happen.
  - After acquiring, write `{"pid", "owner", "started_at"}` to `crawl.lock.json`.
  - **Never probe a PID with `os.kill`.** On Windows, `os.kill(pid, 0)` terminates the process.
- **Tests first:**
  - Acquire, release, then acquire again.
  - A second `CrawlLock` on the same path fails while the first is held.
  - Cross-process: a child process (`subprocess` running `python -c …`) holds the lock and the parent fails to acquire. After `proc.kill()`, the parent acquires.
  - `holder()` returns the owner and PID.
  - **Spider:** with the lock held elsewhere, `TDSpider.start()` yields nothing and closes the spider with reason `locked`. Drive it with `asyncio.run` over the async generator, with a mocked `crawler.engine`.
- **Implementation:**
  - At the top of `TDSpider.start()`, before anything is yielded, acquire `CrawlLock(self.data_dir / "crawl.lock", owner=self.name)`.
  - If the lock is held, log the holder at ERROR level, call `self.crawler.engine.close_spider(self, "locked")` and return. Every request originates in `start()` or in a callback, so a locked spider sends **zero** requests, robots.txt included.
  - `closed()` releases the lock.
  - `fetch_fixtures.py` wraps its fetch loop in the lock. It uses `THREEDECKS_DATA_DIR`, or the default `data/threedecks`. If the lock is held, it prints the holder and exits 1.
- **Done when:** the new tests are green, and the existing tests, the resume tests included, are unchanged and green.

### Task S3: Base spider hardening

The ship plan (4.3) promises these, but the code doesn't do them yet.

- **Files:** `spiders/base.py`, `parsing/ship_page.py` (add `has_footer`; S4 moves it), `tests/test_spiders.py`. Footer additions go in `tests/fixtures/synthetic/ship_full.html`, `ship_minimal.html` and the `SHIP_PAGE` template in `tests/resume_harness.py`.
- **The only allowed edit to existing fixtures:** add `<span id="copywrite_message">Copyright</span>` before `</body>` in those three places.
- **The behaviour:**
  1. **Parser exceptions → `parse_error`.** Today an exception escapes the callback and the page stays `pending` forever. Wrap the parse call in `try/except Exception`. Mark `parse_error` with `last_error = f"{type(e).__name__}: {e}"`, log with `logger.exception`, and continue.
  2. **Network failures → `error`, with attempts counted.** Every request the base builds gets `errback=self.on_request_error`. It marks `error` with `increment_attempts=True`. For an `HttpError` with status 403 or 429, mark `error` with `last_error="blocked"` and **don't** count an attempt: the block isn't the page's fault.
  3. **Completeness includes the footer.** Every real page ends with `span#copywrite_message` ("Copyright © Cy Harrison 2010-2026…"). A ship page counts only if `is_ship_page(sel) and has_footer(sel)`; otherwise it takes the existing incomplete path (drop the cache entry, mark `error`, retry once). Not-found pages don't need the footer.
  4. **Stats.** `_stat(key, n=1)` does nothing without a crawler. Keys:
     - `threedecks/<kind>/parsed`, `not_found`, `incomplete`, `parse_error` and `network_error`
     - `threedecks/<kind>/unknown_label/<label>` and `threedecks/<kind>/unknown_section/<heading>`

     `<kind>` is `ship` for now.
  5. **`runs.pages_fetched`** becomes the sum of parsed, not_found and incomplete, not `item_scraped_count`.
- **Tests first:**
  - **Parse error:** `monkeypatch` `threedecks.spiders.base.parse_ship` to raise `ValueError("boom")`. `parse_ship_page` yields nothing, the status is `parse_error`, and `last_error` contains `ValueError: boom`.
  - **Errback:** a `twisted.python.failure.Failure(TimeoutError())` with `.request` set to a ship request → `error`, with attempts +1. A Scrapy `HttpError` for a 429 response → `error`, `last_error == "blocked"`, attempts unchanged.
  - **Footer:** a synthetic ship page without the footer → `error`, one retry request, and the cache entry dropped.
  - **Real pages:** a `real_pages` test asserts that every real fixture `has_footer`.
  - **Stats:** with a crawler-backed spider (`scrapy.utils.test.get_crawler`), check `parsed`, `not_found`, `unknown_label/<label>` (the existing synthetic unknown label) and `unknown_section/<heading>`.
  - **Runs:** `pages_fetched` equals the sum above.
- **Done when:** green, with only the listed fixture edits.

### Task S4: `parsing/common.py`

A pure refactor.

- **Files:** `parsing/common.py` (new), `parsing/ship_page.py`, `tests/test_common.py` (new).
- **Move:** `_norm`, `_kind`, `_links`, `_node_text`, `_int_from_text`, `_parse_sources` and `has_footer` move from `ship_page.py` into `common.py` as `norm`, `link_kind`, `links`, `node_text`, `int_from_text`, `parse_sources` and `has_footer`. `ship_page.py` imports them. Grep `tests/` for any private name a test imports, and keep an alias for it.
- **Add** `text_without_tooltips(node) -> str`. It joins descendant text nodes, excluding any inside `span.tooltiptext` or `span.hidden`, then normalises whitespace. Every `div.tooltip` on action and fleet pages carries hover text ("British<br>Naval Sailor<br>Service 1782-1840"), which must never leak into names or notes.
- **Tests first:** `text_without_tooltips` on a synthetic tooltip snippet returns only the anchor text; `has_footer` gives True and False.
- **Done when:** every ship parser test passes **unchanged**.

### Task S5: Generic page frontier

The ship `frontier` table is keyed by `td_id`. Action and fleet IDs are separate ID spaces (battle 157 is not ship 157). Changing `frontier`'s primary key would mean rebuilding a table the ship spiders depend on, so this task adds a separate table instead. It's created with `CREATE TABLE IF NOT EXISTS`, so it's safe to deploy even in the middle of a ship crawl.

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
  page_counts_by_status(kind) -> dict[str, int]
  _page_done_sql(kind, key, now) -> None   # executes the "mark done" upsert WITHOUT committing, so a
                                           # kind-specific save_*() can write record + done in ONE transaction
  ```

  `counts_by_status()` stays ship-only and unchanged.
- **Tests first:**
  - Seeding is idempotent, and `seed_pages` returns only the new keys.
  - Numeric order: "10" comes after "9".
  - Namespaces are separate: ship 157 `done`, page (x, "157") still `pending`.
  - Attempts count up and cap.
  - `page_counts_by_status`.
  - Reopening keeps everything.
  - **Old schema:** build `state.sqlite` with a copy of the pre-S5 `_SCHEMA` text (paste it into the test as `OLD_SCHEMA`), insert a ship and a frontier row, then open it with the new `StateStore`. Both rows are intact and `page_frontier` exists.
- **Done when:** green, and every existing state test is unchanged.

### Task S6: `PageKind` registry and a kind-agnostic base

- **Files:** `threedecks/pages.py` (new), `spiders/base.py`, `tests/resume_harness.py`, `tests/test_spiders.py`.
- **`pages.py`:**

  ```python
  @dataclass(frozen=True)
  class PageKind:
      name: str                                  # 'ship', later 'action' / 'fleet'
      display_type: str                          # 'show_ship', later 'show_battle' / 'show_fleet'
      is_page: Callable[[Selector], bool]
      is_not_found: Callable[[Selector], bool]
      parse: Callable[..., object]               # (selector, url, *, fetched_at, content_sha256, parser_version)
      parser_version: str
  KINDS: dict[str, PageKind] = {}
  def register(kind: PageKind) -> PageKind: ...  # KINDS[kind.name] = kind; idempotent
  SHIP = register(PageKind("ship", "show_ship", is_ship_page, is_not_found_page, parse_ship, PARSER_VERSION))
  ```

  Each Part B adds its own kind in its own module, by calling `register`. Neither Part B edits the other's kind.
- **Base (`TDSpider`):**
  - `entity_url(kind, id)`, then `f"{base_url}/index.php?display_type={KINDS[kind].display_type}&id={id}"`.
  - `entity_request(kind, id, *, depth=0, discovered_by=None, priority=0)`, with meta `{kind, key, depth, discovered_by}` (plus `td_id` when the kind is ship), the S3 errback, and `dont_filter=True`.
  - `parse_entity_page(response)`: one handler for every kind, running not-found → completeness (`is_page` and `has_footer`) → parse in try/except → stats, in that order.
  - `_mark(kind, key, status, **kw)` routes `ship` to `store.mark_status(int(key), …)` and every other kind to `store.mark_page_status(kind, key, …)`.
  - `stream_pending_pages(kind)`.
  - `ship_request` and `parse_ship_page` remain as ship wrappers, so `ShipsAllSpider` and the existing tests work unchanged. A missing `kind` in meta means `ship`.
- **Harness:**
  - `run_crawl(..., spider="ships_all")` and `start_crawl(..., spider="ships_all")`. Existing callers are unchanged.
  - Refactor `FakeSite` so that `GET /index.php` and `POST /index.php` dispatch on `display_type` through `self.handlers: dict[str, Callable]`, with the ship handler registered by default.
  - Count requests per `(display_type, key)`. Keep `count(td_id)` and `total_ship_requests` as ship wrappers.
  - Add an optional per-response `delay` (seconds) and a `blocked: set[tuple[str, str]]` of `(display_type, key)` pairs answered with 429. The existing `block_id` and `block_active` keep working for ships.
  - Each Part B adds its own handlers in its own helper function, never by editing the other's.
- **Tests first:**
  - `entity_request("ship", 5)` equals `ship_request(5)` in URL and meta.
  - `parse_entity_page` with the ship kind behaves exactly like `parse_ship_page` on the synthetic fixtures (done, not_found, incomplete).
  - The `FakeSite` handler registry serves ships exactly as before.
- **Done when:** green, and every ship spider and resume test is unchanged.

## 7. Part B: the actions crawler (tasks A1–A9)

Each task lists its files, the tests to write first, implementation notes, and its exit criterion ("Done when").

### Task A1: Long-form dates

- **Files:** `parsing/dates.py`, `tests/test_dates.py`.
- **New function `parse_long_date(text) -> tuple[TDDate | None, TDDate | None]`:**
  - Normalise whitespace, then split on ` - ` **outside parentheses** into a start part and an optional end part.
  - In each part, a trailing `(YYYY/MM/DD NS)` sets `gregorian_iso`.
  - The main text matches one of three forms:
    - `(\d{1,2})\s*(st|nd|rd|th)?\s+(of\s+)?<Month>\s+(\d{4})` → day precision
    - `<Month>\s+(\d{4})` → month precision
    - `(\d{4})` → year precision
  - A leading weekday is ignored. `raw` is the part's text. An unparseable part gives `TDDate(raw=part)` with precision None. Empty text gives `(None, None)`.
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
- Add the section 4.1 dataclasses: `ActionIndexRow`, `ActionIndexPage`, `ActionSide`, `ActionDivision`, `Participant`, `ActionRecord`.
- **Test:** each type survives a round trip through `dataclasses.asdict` and `json.dumps`.
- **Done when:** green.

### Task A3: Action parsers

- **Files:** `parsing/actions.py` (new), `tests/test_actions.py` (new). New synthetic fixtures: `tests/fixtures/synthetic/action_full.html`, `action_minimal.html`, `action_index.html` and `action_notfound.html`.
- **API:**

  ```python
  ACTION_PARSER_VERSION = "1"
  def is_action_page(sel) -> bool          # table#table_action_info present and h1 text non-empty
  def is_action_not_found(sel) -> bool     # not is_action_page and <title> starts "Find an action" (case-insensitive)
  def is_action_index_page(sel) -> bool    # table#table_actions_list present
  def parse_action_index(sel) -> ActionIndexPage
  def parse_action(sel, url, *, fetched_at="", content_sha256="", parser_version=ACTION_PARSER_VERSION) -> ActionRecord
  ```

- **Index:**
  - The rows are `table#table_actions_list tr` that have a `td.col_battle`.
  - Dates come from the `span[@title]` elements in `td.col_battle_dates`, through `parse_td_date(text, title)`. With two spans, the second is `end_date`.
  - `action_type` is `td.col_action_type`. `war_id` and `war_text` come from `td.col_war`, which may be empty.
  - `cells` holds each `td`'s text, without tooltips.
  - `total` comes from "N Records Found" (strip the commas); `page` and `pages` come from "Showing Page N of M".
  - A row without a battle link gets `battle_id=None`.
- **Action page,** scoped to `div#datacol`:
  - **Header:** the first child `div` of `#datacol` that contains a `strong` element and precedes `table#table_action_info`.
    - `header_text` is its full text.
    - The date is `parse_long_date` on the text before the first `<br>`.
    - Labelled lines: `Part of :` gives `war_id`/`war_text`; `Fought at :` gives `places` (every `show_shipyard` link, through `common.links`); `Previous action :` and `Next action :` give their `show_battle` IDs.
  - **Coordinates:** apply `position:\s*new google\.maps\.LatLng\(\s*([-\d.]+)\s*,\s*([-\d.]+)\s*\)` to the script text inside `div#actionmapholder`. Without a map, both values are None.
  - **`table#table_action_info`:** iterate its `tr` elements in order and classify each one:
    - **Side heading** (`th/h2`): a new `ActionSide` with the label from `text_without_tooltips`, plus its `show_nation` and `show_crewman` IDs. Reset the current division.
    - **Division heading** (`th[@colspan]/span`): a new `ActionDivision`, with `side_index` set to the current side.
    - **Division note** (`tr.action_div_notes`): append to the current division's notes. With no division, append to `unknown_rows`.
    - **Participant** (has `td[contains(@class,'column2')]`):
      - `td_id` and `ship_label` come from the first `show_ship` anchor's own text. Without an anchor, `td_id` is None and the label is the cell text without tooltips.
      - The commander comes from the 2nd `td`: `commander_text` is None when the cell is blank.
      - `notes` is the 3rd `td` without tooltips; `flags` holds its `strong` texts.
    - **Column header** (contains "Ship Name") or **spacer** (only whitespace or nbsp): skip.
    - **Anything else:** `unknown_rows.append(norm(text)[:200])`.
  - **`notes`:** the text of `div#table_page_notes` minus its `h2`, or None.
  - **`sources`:** `common.parse_sources`.
  - **`unknown_sections`:** every `h2` in `#datacol` outside `table#table_action_info` other than "Notes on Action", "Sources" and "Recent comments to other pages". Never read `table#comment_list_table`.
  - **`battle_id`:** `extract_id(url)`.
- **Synthetic fixtures,** each quirk from 3.2 once:
  - **`action_full.html`:**
    - a header with a range, "Part of", "Fought at" with 2 links, and Previous/Next
    - a map script with the commented line plus the `position:` line
    - side 1 with two nations and a tooltip commander; two divisions (one with a commander) and one division note
    - participants: one with a flag and notes, one with nbsp as commander, one with no ship link
    - side 2 with one division
    - one unknown row (`<tr><td colspan="2">odd</td></tr>`)
    - Notes on Action, a source list and an unknown `h2` section
    - a comment table containing `show_ship` links
    - the footer
  - **`action_minimal.html`:** one side, no divisions, no map, no notes, no war.
  - **`action_index.html`:** 3 rows (a range with a war, a single date with an empty war cell, and a row without a battle link), plus "N Records Found" and "Showing Page 1 of 2".
  - **`action_notfound.html`:** title "Find an action", the index table, and no `table_action_info`.
- **Golden tests** (`real_pages`), from section 3:
  - **157:** name "Battle of Trafalgar"; date 1805-10-21; war 20; previous 532, next 158; (36.29299, -6.25534); sides [7, 4] and [1]; 8 divisions; 73 participants, all with `td_id`; 2682 among them; the first participant is `td_id` 2657, label "Neptuno (80)", commander 16313, notes "37 Killed, 47 Wounded Captured"; one participant flagged "Squadron Flagship"; 2 sources; notes not None.
  - **149:** 55 participants; 2682 among them and **112 not**; sides [7] and [1]; 6 divisions; war 19; 684/217; no coordinates; 0 sources.
  - **532:** 2 participants; sides [1] and [4]; 0 divisions; war 20; 199/157.
  - **988:** start 1563-05-22 (gregorian 1563-05-31) and end 1563-07-31 (gregorian 1563-08-09); places [95, 1222]; no war; 1 side [1]; 1 division "English Vessels" with 1 note; 5 participants; (49.49, 0.1).
  - **Across all four:** `unknown_rows == []`, `unknown_sections == []`, and no participant field contains "Naval Sailor" (that would be leaked tooltip text).
  - **`action_notfound_probe`:** `is_action_not_found` is True and `is_action_page` is False.
  - **`action_index`:** 50 rows; total 1089; page 1 of 22; the first row is 1145, "Battle of Damme", 1213-05-30 to 1213-05-31, "Fleet action", war 112; 15 rows have an `end_date`; 8 have no war.
  - **`action_index_p2`:** page 2 of 22; the first row is 938, "Battle of Sluis", 1603-05-26.
  - **Cross-check:** parse `ship_2682.html`. For each battle ID in its history that has a fixture (149, 157), 2682 is a participant.
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

- **Files:** `parsing/actions.py` or a new `threedecks/kinds_actions.py`, `pages.py` (an import only, if needed), `pipelines.py` (additions only), `tests/test_pipelines.py`.
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
                                           # errback, dont_filter=True, priority=10
      def parse_index(self, response): ...
  ```

- **`parse_index`:**
  1. **Not-found check first,** although an index page can't really be one.
  2. **Completeness:** `is_action_index_page` and `has_footer`. Otherwise take the incomplete path (drop the cache entry, mark `error`, retry once).
  3. **Parse** in try/except, recording `parse_error` on failure.
  4. **Store:** `save_action_index_page(key, rows)`.
  5. **More index pages:** `seed_pages("action_index", 2..pages)`. Yield `index_request` for **newly inserted** keys only.
  6. **Actions:** `seed_pages("action", ids, discovered_by="action_index")`. Yield `entity_request("action", id)` for newly inserted keys only.
  7. **Stats:** `threedecks/action_index/rows` and `threedecks/action_index/row_without_id`.
- **Action pages** go through `parse_entity_page` with the `ACTION` kind.
- **Tests first:**
  - On an empty store, `start_requests` yields exactly one POST, whose form data equals `action_index_form(1)`.
  - **History seeding:** save a ship whose history has `battle_ids [149, 157]`. `start_requests` yields the index request, then action requests for 149 and 157.
  - **`parse_index` on synthetic `action_index.html`:** the rows are stored, page 1 is `done`, page 2 is seeded and requested once, and each linked action is requested once. A second call on the same response yields no requests.
  - **The not-found probe** isn't parsed as an index.
  - **Separation:** collect every request from `start_requests`, `parse_index` and `parse_entity_page` over all the synthetic action fixtures. Each URL contains `select_action` or `show_battle`, and nothing else (no `show_ship`, `show_fleet`, `show_fleetlist`, `show_shipyard`, `show_war` or `show_crewman`).
  - `ActionsSpider` defines no `custom_settings`.
- **Done when:** green.

### Task A7: Resume and lock tests

- **Files:** `tests/resume_harness.py` (an `add_action_routes(site, action_ids)` helper, additions only), `tests/test_resume_actions.py` (new).
- **The routes:**
  - **POST `select_action`:** read `page` and `limit` from the urlencoded body. Serve a minimal index page in the 3.1 markup, with "N Records Found", "Showing Page p of P", rows and the footer.
  - **GET `show_battle`:** a minimal action page with `h1`, `table#table_action_info`, one side, one participant and the footer, or the "Find an action" page for unknown IDs.
- **Tests** (mirror `tests/test_resume.py`):
  - **Graceful stop:** 120 actions, so 3 index pages. The first run stops with `CLOSESPIDER_ITEMCOUNT=40`, and a rerun completes. Every action is `done` once, the server saw each action and each index page once, and the export has 120 unique actions.
  - **Hard kill:** `proc.kill()` after 40 items, then a rerun. At most one action is fetched twice.
  - **Truncated cache entry:** plant a footer-less body for one action in `httpcache.sqlite`. The rerun refetches it, and the record is complete.
  - **Interrupted index sweep:** a 429 on index page 2 closes the run as `blocked`, with page 1 `done`. After the block clears, a rerun fetches pages 2 and 3, and never page 1 again.
  - **Crawl lock:**
    1. Start `ships_all` against a `FakeSite` with `delay=0.3`, and wait until it has requested a ship.
    2. Run `actions` against the same data dir. It exits; its latest `runs` row has `close_reason == "locked"`; the site saw **zero** `select_action` or `show_battle` requests.
    3. `proc.kill()` the ship crawl. Then `actions` runs to completion.
  - **Namespaces:** ship 157 and action 157 both exist. Run `ships_all`, then `actions`. Both are stored, and both frontier rows are `done`.
- **Done when:** green. Keep the new tests under about 2 minutes in total.

### Task A8: Scripts

All changes are additions. Don't restructure what the ship code or the fleets plan has, or will have.

- **`crawl_status.py`:** an "actions" block giving the `action_index` and `action` status counts, the actions stored, and the last `actions` run with its ETA.
- **`reparse.py`:**
  - If `--kind` doesn't exist yet, add it, with `ship` and `all` among the choices. Then add `action` and `action_index`.
  - `show_battle` URLs are reparsed with `parse_action`. A cached `select_action` response (every index POST has the same URL) takes its page key from the parsed "Showing Page N".
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
  - `action_participants.parquet`: `battle_id`, `side_index`, `side_label`, `side_nation_ids`, `division_label`, `td_id`, `ship_label`, `commander_ids`, `notes` and `flags`.
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
  - **Reparse:** a cache DB written with `SqliteCacheStorage`, holding one action page, gives a stored record.
  - **Status:** the output contains the actions block.
- **Done when:** green.

### Task A9: Docs and final check

- **Ship plan, section 4 tree:** add `lock.py`, `pages.py`, `forms.py`, `parsing/common.py`, `parsing/actions.py` and `spiders/actions.py`. Note in 4.3 step 6 that completeness now includes the footer.
- **Final check:** `uv run ruff check` clean, and `uv run pytest -q` green. Then report back (section 8).

## 8. Report back

When finished, or when stopped by a rule in 5.2, report:

- one line per task (S1–S6, A1–A9): done / skipped (already done) / blocked, and its commit hash
- the final `pytest` summary line and the `ruff` result
- any deviation from this plan, with the reason
- any real-fixture number that disagreed with section 3
- open questions for the operator

## 9. Operator runbook (human only; not for the agent)

Open a **new** terminal, so the `THREEDECKS_CONTACT` user variable is visible. Scrapy commands run inside `scrapers/threedecks/`; scripts run from the repo root. The crawl lock refuses to start a second crawl while one is running.

1. **Ship smoke test,** if it hasn't been done since S1: `uv run scrapy crawl captures -s CLOSESPIDER_PAGECOUNT=25`. It passes if it doesn't close as `blocked`.
2. **Tier A,** if not done yet: `uv run scrapy crawl captures` (about 1.7 h).
3. **Actions smoke test:** `uv run scrapy crawl actions -s CLOSESPIDER_PAGECOUNT=25`.
   - The closing stats must show no `threedecks/action/parse_error`, `unknown_row` or `unknown_section`.
   - Then rerun, press Ctrl+C after about 10 pages, and rerun again. It must continue where it stopped.
4. **Tier D:** `uv run scrapy crawl actions` (about 2.1 h). Then:
   - `uv run python scripts/crawl_status.py`
   - `uv run python scripts/qa_report.py --out data/threedecks/exports/qa.md`
   - Decide on D-gap from the "fetched IDs missing from the index" count.
5. **After the ship crawl's Tier C:** rerun `uv run scrapy crawl actions`. It fetches only the newly cited battle IDs.
6. **Export:** `uv run python scripts/export.py`.
