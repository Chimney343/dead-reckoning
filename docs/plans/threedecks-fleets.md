# Three Decks fleets: plan

Status: 2026-10-08. Permission granted. Recon done. Ready to execute.

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
- **What it shares with the ship crawler:** the settings, the HTTP cache file, the state file (separate tables), the crawl lock and the base spider.
- **It never runs at the same time as any other crawl.** Rule 10 and the crawl lock enforce this.

### 1.3 Out of scope

Ship, action, place, crewman and source pages (kept as IDs); geocoding; and anything about actions.

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
- **Tooltips.** Every `div.tooltip` carries a `span.tooltiptext` (ship years and rate, or crewman nationality and service). It **must be excluded** from labels, names and notes.
- **Other sections.** `div#source_list` uses the ship markup. The comments block ("Recent comments to other pages", `table#comment_list_table`, which contains `show_ship` links) is ignored.
- **Golden numbers:**

  | Fleet | Commander | Formed / disbanded | Ships | Events | Sources | Other |
  |---|---|---|---|---|---|---|
  | 97, Saumarez's Squadron 1798 | [4757] | 1798-08-14 / 1798 | 13 (7 distinct commanders) | 1, linking place 1740 (Aboukir Bay) | 1 | — |
  | 139, Miguel Enriquez's privateer fleet | 1 crewman | — | 33 | 40, the first dated `c.1704` | 1 | an Introduction |

### 3.3 Not-found and completeness

- **A missing fleet ID** returns a shell: the title is "Fleet details", the `h1` is empty, and the only table is a base table with empty Formed and Disbanded values. There is no ships table.
- **Every real page ends with `span#copywrite_message` and `</html>`.** A response without the footer is incomplete (Part A, S3).

### 3.4 Data-quality signals (keep raw; never reconcile in the scraper)

- **Fleet dates are often year-only or approximate** (`1798`, `c.1704`). Keep the raw value and the precision.
- **Places are `show_shipyard` records** ("Aboukir Bay", 1740). There are no coordinates on fleet pages.
- **Ship joined and left dates may fall outside the ship's own lifecycle.** QA reports these; nothing is reconciled.

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
    cells: list[str]                                  # lossless, the 5 cells' text without tooltips

@dataclass
class FleetShip:
    td_id: int | None; ship_label: str                # "Orion (74)"
    joined: TDDate | None; left: TDDate | None
    commander_ids: list[int]; commander_text: str | None
    notes: str
    cells: list[str]                                  # lossless, every td's text without tooltips

@dataclass
class FleetEvent:
    date: TDDate | None
    text: str
    ship_ids: list[int]; place_ids: list[int]; battle_ids: list[int]   # IDs only; never followed
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

1. **`start()`** takes the crawl lock (S2).
2. **Seed** `fleet_index` "1". If it's pending, yield a GET of `show_fleetlist` at priority 10. Then stream the pending fleets in ascending ID order.
3. **Index callback:**
   - Run the completeness check.
   - Parse, then save the rows and mark the page `done` together.
   - Seed the fleet IDs (`discovered_by='fleet_index'`), and request only the **newly inserted** ones.
4. **Fleet page callback:** the shared `parse_entity_page` with the `FLEET` kind yields a `FleetRecord`, which the pipeline stores with `save_fleet`.

### 4.4 Size and order

| Run | Requests | Time |
|---|---|---|
| E-smoke | index + 24 fleet pages (`-s CLOSESPIDER_PAGECOUNT=25`) | ~3 min |
| Tier E | 1 index GET + 146 fleet pages | ~17 min |

The agreed run order is: ship smoke test → Tier A → actions → **fleets** → Tier C. The fleets crawl doesn't depend on any of the others, so it can run at any point when no other crawl is running.

## 5. Before you start

### 5.1 Read first

- **This plan:** all of it. Section 3 is the markup reference for every parser task.
- **The ship plan:** 2.3, 4.2, 4.3 and 6.
- **Code:**
  - `scrapers/threedecks/threedecks/`: `settings.py`, `middlewares.py`, `cache.py`, `state.py`, `items.py`, `pipelines.py`, `spiders/base.py`, `spiders/ships_all.py`, `parsing/ship_page.py`, `parsing/grid.py`, `parsing/dates.py`
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
   - Don't create, import or modify anything action-specific: `parsing/actions.py`, `spiders/actions.py`, `forms.py`, action items, action tables.
   - Shared files (`items.py`, `state.py`, `pipelines.py`, `resume_harness.py`, the scripts) only gain **additions**. Never restructure code the actions plan may also add to.
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
- **Git:** work on branch `data-layout`. Commit after each task: `Three Decks S<n>: <title>` for Part A, `Three Decks fleets FL<n>: <title>` for Part B. Never push.

### 5.4 Baseline and Task 0

- **Before Part A** (measured 2026-10-08): `uv run pytest -q` gives **177 passed, 54 deselected** (the deselected tests are network-marked), and `uv run ruff check` is clean.
- **If Part A is already done**, because the actions plan ran first: there are more tests, and all of them must pass.

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

## 7. Part B: the fleets crawler (tasks FL1–FL9)

Each task lists its files, the tests to write first, implementation notes, and its exit criterion ("Done when").

### Task FL1: Approximate dates

- **Files:** `parsing/dates.py`, `tests/test_dates.py`.
- **Change:** `parse_td_date` accepts the qualifier `c.` (and `c ` followed by a digit) the same way it accepts `bef.`.
- **Tests:**

  | Input | Qualifier | ISO | Precision |
  |---|---|---|---|
  | `c.1704` | `"c."` | `"1704"` | year |
  | `c.4.1788` | `"c."` | `"1788-04"` | month |
  | `c 1704` | `"c."` | `"1704"` | year |
  | `cat` | — | unparsed, raw kept | — |

- **Done when:** green; the existing date tests are unchanged.

### Task FL2: Fleet items

- **Files:** `items.py` (additions only), `tests/test_items_fleets.py` (new).
- Add the section 4.1 dataclasses: `FleetIndexRow`, `FleetShip`, `FleetEvent` and `FleetRecord`.
- **Test:** each type survives a round trip through `dataclasses.asdict` and `json.dumps`.
- **Done when:** green.

### Task FL3: Fleet parsers

- **Files:** `parsing/fleets.py` (new), `tests/test_fleets.py` (new). New synthetic fixtures: `tests/fixtures/synthetic/fleetlist_index.html`, `fleet_full.html` and `fleet_notfound.html`.
- **API:**

  ```python
  FLEET_PARSER_VERSION = "1"
  def is_fleet_page(sel) -> bool            # h1 non-empty and a table.column8 whose first-cell labels include "Fleet Formed"
  def is_fleet_not_found(sel) -> bool       # <title> == "Fleet details" (stripped, case-insensitive) and h1 empty
  def is_fleetlist_index_page(sel) -> bool  # an h1 "Fleets" and at least one show_fleet link in #datacol
  def parse_fleet_index(sel) -> list[FleetIndexRow]
  def parse_fleet(sel, url, *, fetched_at="", content_sha256="", parser_version=FLEET_PARSER_VERSION) -> FleetRecord
  ```

- **Index:**
  - Take the cells as `(//div[@id='datacol']//table)[1]/tbody/td | …/tbody/tr/td`, in document order. This keeps working if the site ever adds `tr` rows.
  - Chunk them in fives, in the order of section 3.1.
  - Dates go through `parse_td_date(text, title)`. `nation_id` is None when the cell is text. `cells` holds each cell's text without tooltips.
  - If the cell count isn't a multiple of 5, parse the complete rows, then raise `ValueError`, so the spider records `parse_error`.
- **Fleet page,** scoped to `div#datacol`. Classify every `table.column8` that isn't `#comment_list_table`:
  - **Base table** (its first-cell labels include "Fleet Formed"):
    - Each row becomes a `BaseRow`: label from the first `td`; text from the other non-`source_col` cells, without tooltips; `date` from a `span[@title]` through `parse_td_date`; `links` through `common.links`; `source_code` from `td.source_col a`.
    - Labels outside {Fleet Commander, Fleet Formed, Fleet Disbanded} go to `unknown_labels`.
    - `commander_ids` come from the Fleet Commander row's `show_crewman` links; `formed` and `disbanded` come from their rows' dates.
  - **Ships table** (its `th` texts include "Ship" and "Joined"). Each data row becomes a `FleetShip`; pick cells by class and content, never by position:
    - `td_id` and `ship_label` come from the `show_ship` anchor's own text.
    - `joined` and `left` come from the first and second `td.column1` in the row.
    - The commander comes from the `td.column2` holding a `show_crewman` link. Otherwise `commander_ids` is `[]`, and `commander_text` is None when that cell is nbsp.
    - `notes` is the last `td.column2`, and `cells` holds every `td`'s text without tooltips.
  - **Events table** (its header includes "Date" and "Event"). Each data row becomes a `FleetEvent`:
    - The date is `parse_td_date(text, title)` when there's a `span.date_field`, otherwise `parse_td_date(text)`, which covers `c.1704`.
    - `text` is `td.col_info_text` without tooltips. Collect its `ship_ids` (`show_ship`), `place_ids` (`show_shipyard`) and `battle_ids` (`show_battle`).
    - `source_code` comes from `td.source_col a`, or None.
  - **Any other `table.column8`:** `unknown_sections.append("table: " + first header text)`.
  - **`introduction`:** the `p` text after an `h2` "Introduction", up to the next `table` or `h2`.
  - **Any other `h2`** (not Introduction, Sources or "Recent comments to other pages") goes to `unknown_sections`.
  - **`sources`:** `common.parse_sources`. **`fleet_id`:** `extract_id(url)`.
- **Synthetic fixtures:**
  - **`fleetlist_index.html`:** a flat `tbody` with 3 fleets: one with nation "Unknown?", one with no commander, and one with tooltip text in the commander cell.
  - **`fleet_full.html`:**
    - a base table with sources, plus one unknown label
    - a ships table with one 7-cell row with a commander and one without
    - an events table with a `date_field` row, a `c.1704` row, and a row linking a ship, a place and a battle
    - an Introduction
    - a comment table with `show_ship` links
    - the footer
  - **`fleet_notfound.html`:** the empty shell from 3.3.
- **Golden tests** (`real_pages`), from section 3:
  - **`fleetlist_index`:** 146 rows; 146 unique IDs; min 1, max 151. Row 1 is `fleet_id` 132, nation text "Unknown?", `nation_id` None, no commander, `date_from` raw "2.1501". `nation_id` 7 rows are fleets {139, 146, 151}.
  - **97:** name "Saumarez's Squadron 1798"; commander [4757]; formed 1798-08-14; disbanded "1798" (year); 13 ships; 1 event with `place_ids == [1740]`; 1 source; `unknown_labels == []` and `unknown_sections == []`.
  - **139:** 33 ships; 40 events; the first event's raw date is "c.1704"; introduction not None; 1 source; no `unknown_*`.
  - **`fleet_notfound_probe`:** `is_fleet_not_found` is True and `is_fleet_page` is False.
  - **No leaks:** no `ship_label`, `commander_text` or `notes` contains "Naval Sailor".
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
  ```

- **Tests first:**
  - `save_fleet` writes the record and `done` together.
  - `save_fleet_index` skips rows without an ID and marks the index `done`.
  - Ship 97 and fleet 97 don't interfere.
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
          self.store.seed_pages("fleet_index", ["1"], discovered_by="start")
          if self.store.page_status("fleet_index", "1") in ("pending", "error") \
                  and self.store.page_attempts("fleet_index", "1") < self.max_attempts:
              yield self.index_request()                         # priority=10
          yield from self.stream_pending_pages("fleet")
      def index_request(self): ...   # GET {base}/index.php?display_type=show_fleetlist,
                                     # meta kind='fleet_index', key='1', errback, dont_filter=True, priority=10
      def parse_index(self, response): ...
  ```

- **`parse_index`:**
  1. **Completeness:** `is_fleetlist_index_page` and `has_footer`. Otherwise take the incomplete path (drop the cache entry, mark `error`, retry once).
  2. **Parse** in try/except, recording `parse_error` on failure.
  3. **Store:** `save_fleet_index(rows)`.
  4. **Fleets:** `seed_pages("fleet", ids, discovered_by="fleet_index")`. Yield `entity_request("fleet", id)` for **newly inserted** keys only.
  5. **Stats:** `threedecks/fleet_index/rows` and `threedecks/fleet_index/row_without_id`.
- **Fleet pages** go through `parse_entity_page` with the `FLEET` kind.
- **Tests first:**
  - On an empty store, `start_requests` yields exactly one GET, to `show_fleetlist`.
  - **`parse_index` on synthetic `fleetlist_index.html`:** the rows are stored, the index is `done`, and each fleet is requested once. A second call yields no requests.
  - When the index is already `done`, `start_requests` yields only the pending fleet requests.
  - **Separation:** collect every request from `start_requests`, `parse_index` and `parse_entity_page` over all the synthetic fleet fixtures. Each URL contains `show_fleetlist` or `show_fleet&`, and nothing else. In particular, there's no `show_battle`, although `fleet_full.html` links a battle in an event, and no `show_ship`, `show_shipyard` or `show_crewman`.
  - `FleetsSpider` defines no `custom_settings`.
- **Done when:** green.

### Task FL7: Resume and lock tests

- **Files:** `tests/resume_harness.py` (an `add_fleet_routes(site, fleet_ids)` helper, additions only), `tests/test_resume_fleets.py` (new).
- **The routes:**
  - **GET `show_fleetlist`:** a flat-cell index in the 3.1 markup, with the footer.
  - **GET `show_fleet`:** a minimal fleet page (`h1`, a base table with "Fleet Formed", a ships table with one ship, the footer), or the "Fleet details" shell for unknown IDs.
- **Tests** (mirror `tests/test_resume.py`):
  - **Graceful stop:** 60 fleets. The first run stops with `CLOSESPIDER_ITEMCOUNT=20`, and a rerun completes. Every fleet is `done` once, the server saw the index once and each fleet once, and the export has 60 unique fleets.
  - **Hard kill:** `proc.kill()` after 20 items, then a rerun. At most one fleet is fetched twice.
  - **Truncated cache entry:** plant a footer-less body for one fleet. The rerun refetches it, and the record is complete.
  - **Blocked:** a 429 on fleet 30 closes the run as `blocked`. After the block clears, a rerun completes, and the index isn't refetched.
  - **Crawl lock:**
    1. Start `ships_all` against a `FakeSite` with `delay=0.3`, and wait until it has requested a ship.
    2. Run `fleets` against the same data dir. It exits; its latest `runs` row has `close_reason == "locked"`; the site saw **zero** `show_fleetlist` or `show_fleet` requests.
    3. `proc.kill()` the ship crawl. Then `fleets` runs to completion.
  - **Namespaces:** ship 97 and fleet 97 both exist. Run `ships_all`, then `fleets`. Both are stored, and both frontier rows are `done`.
- **Done when:** green. Keep the new tests under about 2 minutes in total.

### Task FL8: Scripts

All changes are additions. Don't restructure what the ship code or the actions plan has, or will have.

- **`crawl_status.py`:** a "fleets" block giving the `fleet_index` and `fleet` status counts, the fleets stored, and the last `fleets` run with its ETA.
- **`reparse.py`:**
  - If `--kind` doesn't exist yet, add it, with `ship` and `all` among the choices. Then add `fleet` and `fleet_index`.
  - `show_fleet` URLs are reparsed with `parse_fleet`, and `show_fleetlist` with `parse_fleet_index`.
  - The not-found and completeness rules are the spider's. No network.
- **`export.py`:** adds six files.
  - `fleets.jsonl` and `fleet_index.jsonl`.
  - `fleets.parquet`: `fleet_id`, `name`, `nation_id` (joined from the index), `commander_ids`, `formed_iso`, `disbanded_iso`, `ship_count`, `event_count`, `url`, `fetched_at`, `content_sha256` and `parser_version`.
  - `fleet_ships.parquet`: `fleet_id`, `td_id`, `ship_label`, `joined_iso`, `left_iso`, `commander_ids` and `notes`.
  - `fleet_events.parquet`: `fleet_id`, `date_raw`, `date_iso`, `text`, `ship_ids`, `place_ids`, `battle_ids` and `source_code`.
- **`qa_report.py`:** a "Fleets" section, in both the Markdown and the JSON output. It counts:
  - index IDs not fetched
  - fleet ships with no `td_id`, and fleet ships not found in `ships`
  - fleet ships whose joined or left date falls outside the ship's lifecycle (Launched to its last fate date)
  - `unknown_labels` and `unknown_sections`
  - frontier errors for the `fleet` and `fleet_index` kinds
- **Tests:**
  - **Export:** from a state DB holding two synthetic fleet records, the files exist, the row counts match, and every ship and event row has its `fleet_id`.
  - **QA:** a prepared out-of-lifecycle fleet ship is reported.
  - **Reparse:** a cache DB written with `SqliteCacheStorage`, holding one fleet page, gives a stored record.
  - **Status:** the output contains the fleets block.
- **Done when:** green.

### Task FL9: Docs and final check

- **Ship plan, section 4 tree:** add `lock.py`, `pages.py`, `parsing/common.py`, `parsing/fleets.py` and `spiders/fleets.py`, unless they're already there. Note in 4.3 step 6 that completeness includes the footer, if that isn't noted yet.
- **Final check:** `uv run ruff check` clean, and `uv run pytest -q` green. Then report back (section 8).

## 8. Report back

When finished, or when stopped by a rule in 5.2, report:

- one line per task (S1–S6, FL1–FL9): done / skipped (already done) / blocked, and its commit hash
- the final `pytest` summary line and the `ruff` result
- any deviation from this plan, with the reason
- any real-fixture number that disagreed with section 3
- open questions for the operator

## 9. Operator runbook (human only; not for the agent)

Open a **new** terminal, so the `THREEDECKS_CONTACT` user variable is visible. Scrapy commands run inside `scrapers/threedecks/`; scripts run from the repo root. The crawl lock refuses to start a second crawl while one is running.

1. **Ship smoke test,** if it hasn't been done since S1: `uv run scrapy crawl captures -s CLOSESPIDER_PAGECOUNT=25`. It passes if it doesn't close as `blocked`.
2. **Fleets smoke test:** `uv run scrapy crawl fleets -s CLOSESPIDER_PAGECOUNT=25`.
   - The closing stats must show no `threedecks/fleet/parse_error`, `unknown_label` or `unknown_section`.
   - Then rerun, press Ctrl+C after about 10 pages, and rerun again. It must continue where it stopped.
3. **Tier E:** `uv run scrapy crawl fleets` (about 17 min). Then:
   - `uv run python scripts/crawl_status.py`
   - `uv run python scripts/qa_report.py --out data/threedecks/exports/qa.md`
4. **Export:** `uv run python scripts/export.py`.
