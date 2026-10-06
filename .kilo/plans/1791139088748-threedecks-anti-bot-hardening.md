# Three Decks scraper: anti-bot hardening + Web Bot Auth

Status: planned 2026-10-05. Implements every measure from the 2026-10-04 review of the
Three Decks scraper. All measures are honest-crawler measures: detection, pacing, reaction,
and cryptographic identity. No evasion (UA rotation, proxies, TLS impersonation, stealth
browsers, CAPTCHA solving) — permanently rejected in `docs/plans/threedecks-anti-bot-research.md`.

## Decisions (resolved with the user)

1. **Web Bot Auth**: design and implement it now (signing middleware, keygen, directory
   generator, offline + live tests). Hosting the key directory and Cloudflare registration
   are deferred manual steps with a checklist.
2. **Directory hosting**: build now, host later.
3. **Daily budget / crawl window**: opt-in CLI flags, off by default. No behavior change
   for existing commands.
4. **Request jitter**: uniform 5–7 s gap (`DOWNLOAD_DELAY = 6`, `DOWNLOAD_DELAY_JITTER = 1/6`).
   Floor stays exactly 5.0 s (the owner's robots.txt Crawl-delay). Throughput drops ~17 %
   (≈540 → ≈450 pages/h; Tier C ≈2.4 → ≈2.9 days). Accepted.

## Context

- The crawler is honest and unblocked so far (~1,500 pages, zero 403/429/challenges).
  Politeness contract in `scrapers/threedecks/threedecks/settings.py` + `politeness.py`;
  block handling in `middlewares.py` (cool-offs 15/30/60 min, then close `blocked`);
  crash-safe state + cache (`state.py`, `cache.py`); orchestration in `scripts/crawl.py`
  (watchdog, stall restarts, network retries); smoke in `scripts/smoke.py`.
- Verified Scrapy 2.19 facts this plan relies on:
  - Request fingerprints **exclude headers** by default (`scrapy/utils/request.py`:
    "request headers are ignored by default when calculating the fingerprint") — WBA
    signatures cannot break cache hits.
  - `Slot.download_delay = max(0, delay * (1 + U(-jitter, +jitter)))` — delay 6, jitter 1/6
    gives exactly [5.0, 7.0]. AutoThrottle's `mindelay = DOWNLOAD_DELAY` keeps the floor at 5
    even when it raises the delay.
  - `HttpCacheMiddleware` priority is 900 in `DOWNLOADER_MIDDLEWARES_BASE`; `process_request`
    runs in ascending priority order.

## Phase A — close the block-page detection gap (correctness fix)

**Files**: `threedecks/middlewares.py`, `threedecks/cache.py`, `tests/test_middleware.py`,
`tests/test_cache.py`.

Today `is_challenge` matches only `cf-mitigated: challenge`. Cloudflare also emits
`cf-mitigated: blocked` with a "Sorry, you have been blocked" page. At status 403 that is
already stopped as a plain 403, but at any other status it passes as a normal response:
the consecutive-block counter resets, ship pages burn attempts as `error`/`incomplete`,
and — worst — the block page is **cached** and replayed on later runs. For the captures
POST, a 200 block page would silently wipe the stored capture rows and "finish" the tier.

1. Add `BLOCKED_MARKERS = (b"sorry, you have been blocked",)` (lowercased body scan; the
   phrase is second-person and cannot appear in ship-history prose). Keep
   `CHALLENGE_MARKERS` unchanged (a bare `challenge-platform` script is still not a marker).
2. Add `mitigation(response) -> str | None`: lowercased `cf-mitigated` header value
   (`"challenge"` / `"blocked"` / other / None).
3. Add `is_blocked(response) -> bool`: `mitigation == "blocked"` OR any `BLOCKED_MARKER`
   in the body — **any status, including 200**.
4. `BlockDetectionMiddleware.process_response`: classify three ways.
   - `is_blocked` → the immediate-stop path (same as plain 403): log "Cloudflare block
     page", close `blocked`, drop the request. Never cooled off — a WAF block is a
     decision, not a challenge.
   - `is_challenge` or status 429 → cool-off path (unchanged).
   - plain 403 → immediate stop (unchanged).
5. `ThreeDecksCachePolicy.should_cache_response`: also excludes `is_blocked` responses,
   next to the existing `is_challenge` exclusion.
6. Tests:
   - 200 + `cf-mitigated: blocked` → closes `blocked`, no cool-off scheduled.
   - 200 + "Sorry, you have been blocked" body → closes `blocked`.
   - 403 + challenge markers still cools off (existing test, must stay green).
   - Cache policy: a blocked response is not cached (extend `tests/test_cache.py:136-144`).

## Phase B — sliding-window block escalation

**Files**: `threedecks/middlewares.py`, `threedecks/settings.py`, `tests/test_middleware.py`.

The `consecutive` counter resets on any normal response, so an alternating
block → cool-off → 200 → block pattern never escalates: the crawl limps on with a 15-min
pause per block, forever, and the watchdog sees progress.

1. Settings: `THREEDECKS_BLOCK_WINDOW_SECS = 7200` (2 h),
   `THREEDECKS_BLOCK_WINDOW_MAX = 4`.
2. Middleware: keep `self.block_times: deque[float]`; constructor gains
   `block_window_secs`, `block_window_max`, and an injectable `clock=time.time`
   (same pattern as the existing `call_later` injection). On each cool-off-worthy block:
   purge entries older than the window, append `clock()`, and if `len >= max` close
   `blocked` with a distinct log line ("N blocks in M min") — before scheduling the cool-off.
3. `max = 4` is chosen so the existing consecutive sequence is unchanged: three
   back-to-back blocks still cool off at 900/1800/3600 s and the 4th still closes
   (`test_cooloffs_double_then_the_spider_closes` stays green). The window rule only adds:
   4 blocks inside 2 h close even with 200s between them.
4. Tests: alternating 429/200 ×4 within the window → closes on the 4th; blocks spread
   beyond the window (fake clock) → cool-offs continue; existing consecutive tests unchanged.
   Not added to `politeness.PROTECTED` (consistent with `THREEDECKS_MAX_COOLOFFS`).

## Phase C — single-instance lock

**Files**: new `threedecks/lock.py`, `scripts/crawl.py`, `scripts/smoke.py`, new
`tests/test_lock.py`.

Nothing stops two `crawl.py` processes over the same `data/threedecks`: both would fetch
the same pending ids, doubling the request rate against the owner's 5 s condition.

1. `CrawlLock(path)` context manager: open the file, write pid + local ISO timestamp,
   then take an **OS lock** — `msvcrt.locking(fd, LK_NBLCK, 1)` on win32,
   `fcntl.flock(fd, LOCK_EX | LOCK_NB)` elsewhere. The OS releases it on process death
   (crash, kill, power cut) — no stale-lock logic needed. On contention raise
   `CrawlLockHeld(pid, started)` carrying the holder info read from the file.
2. Lock path: `DATA_DIR / "crawl.lock"` — per-data-dir, so tests with tmp dirs are
   unaffected.
3. `crawl.py main()`: acquire after the contact check, hold for the whole chain; on
   `CrawlLockHeld` print `another crawl holds data/threedecks (pid N, started T); its
   log and heartbeat live there` and exit 2. `smoke.py main()`: same lock (a smoke run
   during a crawl would also double the rate).
4. Tests: acquire → second acquire in the same process fails; release → re-acquire works;
   integration (cheap, via the existing `run()` subprocess harness): start one crawl
   against `FakeSite`, start a second → second exits 2 quickly.

## Phase D — daily budget + crawl window (opt-in flags)

**Files**: `threedecks/extensions.py`, `scripts/crawl.py`, `tests/test_pipelines.py`
(extension tests live there today), `tests/test_crawl.py`, plus unit tests for the new
pure helpers.

Both flags off unless passed. When enabled, `crawl.py` waits at the boundary and continues
by itself — the intended use is an unattended multi-day Tier C.

### Extension `CrawlBudget` (`extensions.py`)

- `from_crawler`: reads `THREEDECKS_DAILY_PAGES` (int, 0 = off) and `THREEDECKS_STOP_AT`
  (epoch float, 0 = off); `NotConfigured` when both off. Register at priority 520 next to
  `Heartbeat`.
- Connects `response_received`. **Counting live fetches only**: skip responses whose
  request meta carries `cache_timestamp` (set by `SqliteCacheStorage.retrieve_response`;
  same signal `base.py:216` already uses). Counts robots.txt too — ≤2 pages per tier,
  accepted slop.
- `count >= daily_pages` → close `daily_budget`. `now >= stop_at` → close `window_closed`.
  One close only (guard flag, like `ShipTarget.closing`).

### `scripts/crawl.py`

- Flags: `--daily-pages N` (default 0 = off), `--window HH:MM-HH:MM` (local time, default
  off; overnight windows wrap, e.g. `22:00-06:00`; span < 10 min → `parser.error`),
  `--day-start HH:MM` (default `00:00`: the local hour the budget resets; also the test seam).
- `pages_today(data_dir, day_start)`: `SELECT COALESCE(SUM(pages_fetched), 0) FROM runs
  WHERE started_at >= <boundary>` — boundary = local day-start converted to the UTC ISO
  string the runs table stores. Limitation, accepted: a hard-killed tier records
  `pages_fetched = 0`, so a crash-day undercounts by that tier's unrecorded pages.
- Tier loop: before starting a tier, if budget on and remaining ≤ 0 → log
  "daily budget of N reached; waiting until <day-start>" and `wait_minutes` until the
  boundary (Ctrl+C → exit 130 "stopped while waiting; rerun to resume"). If window on and
  now outside → wait until window start. Pass `-s THREEDECKS_DAILY_PAGES=<remaining>` and
  `-s THREEDECKS_STOP_AT=<window end epoch>` to the tier in `run_tier`'s command
  construction (not through user `-s` overrides, which the politeness guard inspects).
- New close reasons, handled like network retries (no restart charge): `daily_budget` →
  wait until next day-start, rerun the tier; `window_closed` → wait until next window
  start, rerun the tier. Both waits are interruptible.
- Budget/window waits happen inside `keep_awake` (screen stays on by default;
  `--allow-sleep` opts out) — say so in `--help`.
- Pure helpers for unit tests: `parse_window(s)`, `window_wait_seconds(localnow, window)`
  (wrap-aware), `next_day_start(now, day_start)`, `pages_today`.
- Tests: unit tests for the helpers (incl. wrap + parse errors + `pages_today` against a
  planted `state.sqlite`); extension unit tests (live responses counted, cache replays
  excluded, both close reasons fire once); integration via the harness:
  `FakeSite` + `--daily-pages 2 --day-start <one minute from now>` → the tier closes
  `daily_budget`, the crawl waits, resumes at the boundary, finishes; the runs table shows
  `daily_budget` then `finished`. Wall-clock sensitive (~2 min) — keep the existing
  generous timeout.

## Phase E — incomplete-page streak breaker

**Files**: `threedecks/spiders/base.py`, `threedecks/state.py`, `scripts/crawl.py`,
`tests/test_spiders.py`.

A long run of incomplete 200s (truncated pages, junk responses, markup drift) today burns
one attempt per page and grinds through the frontier. Mirror the existing
`_network_streak` design:

1. Setting `THREEDECKS_INCOMPLETE_LIMIT` (default 3, 0 = off); spider property like
   `network_failure_limit`.
2. `TDSpider`: `self._incomplete_streak: list[int]`. In `_record_incomplete`:
   - Append the td_id **only on a first-attempt incomplete** (`meta.completeness_retries`
     absent/0). The page's own in-run retry must not count twice — a single broken ship
     page must not stop the crawl; three *distinct* pages in a row mean systemic trouble.
   - When `len(streak) >= limit`: log error, `store.release_attempts(streak, reason=...)`,
     `_close("incomplete_streak")`, return without yielding the retry.
   - Otherwise behave as today (mark `error`, drop the cache entry, one in-run retry).
3. Clear the streak in `parse_ship_page` whenever the response is a complete, understood
   page (after the not-found check and `is_ship_page` pass). The existing
   `_network_streak.clear()` at the top stays.
4. `state.py`: `release_attempts(td_ids, reason="network down; attempt not counted")` —
   parameterize the message.
5. `crawl.py`: reason `incomplete_streak` → exit 1, verdict:
   "closed 'incomplete_streak': N ship pages in a row failed the completeness check; the
   site may be serving truncated pages or the markup changed. Run scripts/smoke.py,
   investigate, then rerun." No auto-retry (markup drift needs human eyes; this is also
   the backstop for item A's 200 block pages).
6. Tests (offline, fixture responses through `parse_ship_page`, following the existing
   spider-test pattern): 3 distinct incomplete pages → closes `incomplete_streak` and
   releases attempts; a single incomplete page → crawl continues; the same page's
   completeness retry doesn't double-count; a complete page between incompletes clears
   the streak.

## Phase F — end-of-run notification

**Files**: `scripts/crawl.py`, `tests/test_crawl.py`.

A `blocked` close on an unattended run is currently silent. Add a best-effort Windows
toast:

1. `notify(title, body)`: PowerShell 5.1 WinRT toast
   (`[Windows.UI.Notifications.ToastNotificationManager, ...]` boilerplate) via
   `subprocess.run(["powershell", "-NoProfile", "-Command", ...], creationflags=CREATE_NO_WINDOW,
   timeout=10)`; every failure → `log.debug`, never fatal. Also `log.say("notification:
   <title>: <body>")` so it is visible in captured output.
2. Call once at the end of `crawl()` when `status != 0` (covers `blocked`, stalled-out,
   network-down-exhausted, unexpected closes). Not on success or Ctrl+C.
3. Tests: extend the existing blocked-chain integration test to assert `notification`
   appears in stdout. Keep it light — no toast-machinery unit tests.

## Phase G — request jitter 5–7 s

**Files**: `threedecks/settings.py`, `tests/test_settings.py`, `justfile`,
`docs/plans/threedecks-scraper.md` (§5 throughput line only).

1. `DOWNLOAD_DELAY = 6`, `DOWNLOAD_DELAY_JITTER = 1/6` → `delay * (1 ± 1/6)` = [5.0, 7.0] s,
   floor exactly 5.0 s. `AUTOTHROTTLE_START_DELAY = 6` (consistency; clamped by mindelay
   anyway). Update the settings docstring: the gap never falls below the owner's 5 s
   Crawl-delay; jitter only de-regularizes the interval (Scrapy's own "avoid getting
   banned" practice) — not disguise, the UA still identifies the crawler.
2. `tests/test_settings.py`: replace `assert s.DOWNLOAD_DELAY_JITTER == 0` with
   `assert s.DOWNLOAD_DELAY * (1 - s.DOWNLOAD_DELAY_JITTER) >= 5`; bump the
   `AUTOTHROTTLE_START_DELAY` assertion to `>= 6`.
3. `politeness.py` unchanged (`DOWNLOAD_DELAY`/`DOWNLOAD_DELAY_JITTER` already in
   `PROTECTED`; the refusal message's "5 s rate" wording stays true as the floor).
4. `PAUSE_SECS = 10` still exceeds the 7 s max gap — unchanged.
5. Doc touch-ups: justfile recipe comments (`threedecks-crawl-1000` "~1.5 h" → "~2 h",
   `-2000` "~3 h" → "~4 h") and the §5 throughput sentence in the scraper plan.

## Phase H — Web Bot Auth (build now, host later)

**Files**: `pyproject.toml`, new `threedecks/wba.py`, new `scripts/wba_keygen.py`, new
`scripts/wba_directory.py`, `threedecks/settings.py`, new `tests/test_wba.py`,
`docs/plans/threedecks-anti-bot-research.md` (§3.4 status update).

Specs: Cloudflare Web Bot Auth docs, `draft-meunier-http-message-signatures-directory-03`,
RFC 9421, RFC 8037 Appendix A.3.

### Signing (`threedecks/wba.py`)

- `cryptography>=42` added as a direct dependency in `pyproject.toml` (already in the venv
  via scrapy's chain; make it explicit).
- `thumbprint(jwk)`: base64url-no-padding of SHA-256 over the exact bytes
  `{"crv":"Ed25519","kty":"OKP","x":"<x>"}` — lexicographic member order, no whitespace.
- `load_private_key(path)`, `jwk_from_private(key)` (kty OKP, crv Ed25519, x base64url).
- `sign_request(request, key, directory_url, *, created, nonce, expires)` — pure-ish,
  time and nonce injectable for tests. Sets all three required headers:
  - `Signature-Agent: "<directory URL>"` — sf-string: MUST be quoted, MUST be https,
    MUST be a covered component.
  - `Signature-Input: sig1=("@authority" "signature-agent");created=<t>;keyid="<thumbprint>";alg="ed25519";expires=<t+120>;nonce="<b64(32 random bytes)>";tag="web-bot-auth"`
  - `Signature: sig1=:<b64(64-byte Ed25519 sig)>:`
- Signing base string (RFC 9421 §2.5), three lines joined with `\n`, no trailing newline:
  `"@authority": <netloc>` / `"signature-agent": <header value incl. quotes>` /
  `"@signature-params": ` + the Signature-Input value. **Serialize the parameters once
  and reuse the exact bytes in both the header and the base string** — the classic
  byte-mismatch bug; comment it in code. `@authority` = `urlparse(request.url).netloc`
  (as sent in Host).
- `expires` default 120 s (`THREEDECKS_WBA_EXPIRES_SECS`); Cloudflare recommends short
  expiry over nonce-tracking for replay protection.
- `WebBotAuthMiddleware`: `from_crawler` requires `THREEDECKS_WBA_KEY` (path to private
  PEM) and `THREEDECKS_WBA_DIRECTORY` (URL) — else `NotConfigured`, so today's behavior
  is unchanged and overhead is zero. `process_request` signs; logs once when enabled.
  Register in `DOWNLOADER_MIDDLEWARES` at **950** — after the HTTP cache (900), so cache
  replays never reach the signer and only wire-bound requests are signed (robots.txt
  included; it passes through the downloader chain and consistent identity is desirable).
- **Cache invariant** (verified: fingerprints exclude headers): enabling WBA must not
  change request fingerprints or cause refetches. Guard with an explicit test.

### Scripts

- `scripts/wba_keygen.py --out data/threedecks/wba [--force]`: generates private.pem,
  public.jwk, directory.json; prints the keyid and the next steps. Refuses to overwrite
  an existing private.pem without `--force`. The private key lives under `data/`
  (gitignored) and is never committed; the script says so.
- `scripts/wba_directory.py --key PATH --authority <host> [--validity-days 30]`: emits
  the directory document plus the response headers a host must set —
  `Content-Type: application/http-message-signatures-directory+json`,
  `Cache-Control: max-age=86400`, and `Signature-Input`/`Signature` with
  `tag="http-message-signatures-directory"`, components `("@authority";req)`,
  `created`/`expires` (created + validity for static hosting), `keyid` = thumbprint.

### Settings

`THREEDECKS_WBA_KEY = os.environ.get("THREEDECKS_WBA_KEY", "")`,
`THREEDECKS_WBA_DIRECTORY = ""`, `THREEDECKS_WBA_EXPIRES_SECS = 120`, middleware at 950.
Not in `politeness.PROTECTED` (identity, not rate).

### Tests (`tests/test_wba.py`)

- Thumbprint known-answer: RFC 8037 Appendix A.3's worked example (implementer copies the
  exact expected value from the RFC text; the Cloudflare doc pair
  `x="JrQLj5P_89iXES9-vFgrIy29clF9CC_oPPsw3c5D0bs"` →
  `kid="poqkLGiymh_W0uP6PZFw-dvez3QJT5SolqXBCW38r0U"` is a second check).
- Signer golden test: committed **test-only** Ed25519 key + fixed created/nonce → assert
  exact `Signature-Input` and `Signature` strings; round-trip verify with the public key
  over a rebuilt base string.
- Middleware: `NotConfigured` when settings absent; enabled → all three headers present;
  **fingerprint identical with/without signing** (cache invariant); robots.txt signed too.
- Scripts: JWKS matches the private key; directory headers well-formed; no-overwrite guard.
- Live (marked `network`, following `tests/test_live.py` conventions): generate a
  throwaway key, sign a GET to `https://crawltest.com/cdn-cgi/web-bot-auth` → expect
  **401** (well-formed, key unknown). 400 = formatting bug → fail. 200 impossible
  pre-registration. This is the end-to-end format check without registration.

### Docs

Update `docs/plans/threedecks-anti-bot-research.md` §3.4: WBA now implemented (signing
middleware, keygen, directory generator); hosting + registration pending. Registration
checklist (also printed by `wba_keygen.py`):
1. Generate the production key; keep the private key out of git.
2. Host the directory at `/.well-known/http-message-signatures-directory` — a tiny Worker
   that signs per request is preferred (fresh `created`/`expires`); static hosting with a
   long `expires` is the fallback. Validate with Cloudflare's `http-signature-directory`
   CLI.
3. Cloudflare dashboard → Manage Account → Configurations → Bot Submission Form →
   Verification Method "Request Signature" → paste the directory URL and the UA match
   pattern (`dead-reckoning/0.1`).
4. Confirm via crawltest (expect 200 after registration).
5. Optionally tell the site owner.

## Deferred / manual (out of implementation scope)

- Hosting the directory, Cloudflare registration, owner notification — checklist above.
- Any evasion technique — rejected per the research doc; do not add.

## Validation

- After each phase: `ruff check` and `pytest -m "not real_pages"` (the repo's CI commands).
- Existing tests must stay green, especially the cool-off sequence
  (`test_cooloffs_double_then_the_spider_closes`), the settings contract
  (`test_settings.py`), and the crawl chains (`test_crawl.py`).
- After Phase G: run `just threedecks-smoke` once live (~3 min) to confirm the site serves
  normally at the new pacing.
- WBA live crawltest test is network-marked; runs only when live tests are selected.

## Risks

- **Signature-Input byte-exactness** (params serialization) — the classic WBA failure;
  covered by the golden test and the crawltest live test.
- **Fingerprint/cache interplay** for WBA — verified safe against Scrapy 2.19 source and
  guarded by an explicit test.
- Budget counting includes robots.txt (±2 pages/tier) and undercounts after hard kills —
  accepted slop for a politeness heuristic.
- The daily-budget integration test is wall-clock sensitive (~2 min); the `--day-start`
  seam keeps it bounded.
- Toast is best-effort; failures are debug-logged, never fatal.
- Jitter reduces throughput ~17 % — accepted by decision; docs updated to match.

## Implementation order

A → B → C → E → F → G (small, independent) → D → H (larger). Full suite after each phase.
