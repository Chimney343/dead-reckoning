"""Scrapy settings: the politeness contract of rules 1, 2 and 6.

The 5 s floor is the site owner's condition (the robots.txt Crawl-delay).
Scrapy does not read Crawl-delay itself, so it is pinned here: the delay is 6 s
with +-1/6 jitter, so the gap between requests is 5.0-7.0 s and never below
5 s. The jitter only de-regularizes the interval (Scrapy's own "avoid getting
banned" practice), not a disguise: the User-Agent still identifies the crawler.
The settings contract test in tests/test_settings.py stops the floor being
loosened by accident.
"""

from __future__ import annotations

import os
from pathlib import Path

from .ua import build_user_agent, contact

BOT_NAME = "threedecks"
SPIDER_MODULES = ["threedecks.spiders"]
NEWSPIDER_MODULE = "threedecks.spiders"

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("THREEDECKS_DATA_DIR", REPO_ROOT / "data" / "threedecks"))

# The site, unless a test profile points the spiders at a local server.
THREEDECKS_BASE_URL = os.environ.get("THREEDECKS_BASE_URL", "https://threedecks.org").rstrip("/")

USER_AGENT = build_user_agent()
# Scrapy's defaults plus From, the header HTTP defines for the person responsible
# for a robot (RFC 9110, 10.1.2): the contact again, where a site owner looks for it.
DEFAULT_REQUEST_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
    **({"From": contact()} if contact() else {}),
}
ROBOTSTXT_OBEY = True

# --- rate: the owner's condition ------------------------------------------
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 6
# delay * (1 +- 1/6): exactly [5.0, 7.0] s; the floor is the owner's Crawl-delay.
DOWNLOAD_DELAY_JITTER = 1 / 6
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 6  # consistency; the mindelay floor is DOWNLOAD_DELAY
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5

# A 429 or a Cloudflare challenge pauses the crawl, then retries the request
# unchanged: 15, 30, then 60 min (or Retry-After, if longer). A fourth block in a
# row, or a plain 403, closes the spider with reason 'blocked' (middlewares.py).
THREEDECKS_COOLOFF_SECS = 15 * 60
THREEDECKS_MAX_COOLOFFS = 3
# The sliding window: 4 blocks inside 2 h close the spider even when normal
# responses in between kept resetting the consecutive counter (middlewares.py).
THREEDECKS_BLOCK_WINDOW_SECS = 2 * 60 * 60
THREEDECKS_BLOCK_WINDOW_MAX = 4

# Pages take 1-2 s (the captures POST about 8 s). A shorter timeout than Scrapy's
# 180 s lets a dead network be noticed in minutes: after this many fetches in a
# row with no response, the spider closes 'network_down' without charging attempts.
DOWNLOAD_TIMEOUT = 60
THREEDECKS_NETWORK_FAILURES = 3
# Distinct ship pages in a row that fail the completeness check and close the
# crawl 'incomplete_streak' (systemic truncation or markup drift; 0 = off).
THREEDECKS_INCOMPLETE_LIMIT = 3

# 403 and 429 are deliberately absent: RetryMiddleware would re-send within seconds.
# 52x and 530 are Cloudflare failing to reach the site (520 unknown error, 521 down,
# 522/524 timeouts, 523 unreachable, 525 TLS handshake, 530 origin DNS).
CLOUDFLARE_ORIGIN_ERRORS = [520, 521, 522, 523, 524, 525, 530]
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 408, *CLOUDFLARE_ORIGIN_ERRORS]

# --- crash-safe HTTP cache (rule 6, design 4.3) ---------------------------
HTTPCACHE_ENABLED = True
HTTPCACHE_STORAGE = "threedecks.cache.SqliteCacheStorage"
HTTPCACHE_DIR = str(DATA_DIR)
HTTPCACHE_EXPIRATION_SECS = 0
# The cache sees a response before RetryMiddleware does, so every retried status
# must stay out of it: a cached error would be replayed to each retry.
HTTPCACHE_IGNORE_HTTP_CODES = [403, 429, *RETRY_HTTP_CODES]
# Caches everything except robots.txt, which is re-read every run (rule 1).
HTTPCACHE_POLICY = "threedecks.cache.ThreeDecksCachePolicy"

TELNETCONSOLE_ENABLED = False
REMOTE_CONTROL_ENABLED = False  # Scrapy 2.19's localhost code-execution endpoint
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"

ITEM_PIPELINES = {
    "threedecks.pipelines.ValidationPipeline": 100,
    "threedecks.pipelines.StatePipeline": 300,
}
# 585: responses pass HttpCompressionMiddleware (590) first, so the body is
# decoded, and reach the block check before RetryMiddleware (550) can re-send a
# 503 challenge page. 950: after the HTTP cache (900) in process_request, so a
# cache replay is never signed; only wire-bound requests (robots.txt included)
# carry the Web Bot Auth signature.
DOWNLOADER_MIDDLEWARES = {
    "threedecks.middlewares.BlockDetectionMiddleware": 585,
    "threedecks.wba.WebBotAuthMiddleware": 950,
}
# The spiders set request.meta["depth"] themselves (incarnation hops).
# DepthMiddleware would overwrite it with parent depth + 1, so Tier B ships from
# search page N would sit at depth N and their incarnations would be skipped.
SPIDER_MIDDLEWARES = {"scrapy.spidermiddlewares.depth.DepthMiddleware": None}
# Off unless THREEDECKS_SHIP_TARGET > 0: closes the crawl at that many stored ships.
EXTENSIONS = {
    "threedecks.extensions.ShipTarget": 500,
    "threedecks.extensions.Heartbeat": 510,  # data/threedecks/heartbeat.json, every 30 s
    "threedecks.extensions.CrawlBudget": 520,  # off unless crawl.py sets a budget/window
}
THREEDECKS_SHIP_TARGET = 0
# Comma-separated action ids: when set (e.g. the smoke, -s THREEDECKS_ACTION_IDS=343),
# the actions spider fetches only those battles and never touches the index.
THREEDECKS_ACTION_IDS = ""
# Both off (0) by default; scripts/crawl.py --daily-pages/--window set them per tier.
THREEDECKS_DAILY_PAGES = 0
THREEDECKS_STOP_AT = 0

# --- Web Bot Auth (rule 2 identity; off until a key directory is hosted) ---
# Relative key paths resolve from the repo root, not the scrapy subprocess cwd.
_wba_key = os.environ.get("THREEDECKS_WBA_KEY", "")
THREEDECKS_WBA_KEY = (
    str(REPO_ROOT / _wba_key) if _wba_key and not Path(_wba_key).is_absolute() else _wba_key
)
THREEDECKS_WBA_DIRECTORY = ""
THREEDECKS_WBA_EXPIRES_SECS = 120

# No default page cap. Smoke runs pass -s CLOSESPIDER_PAGECOUNT=25.
# No JOBDIR: resuming is handled by StateStore (design 4.3).
