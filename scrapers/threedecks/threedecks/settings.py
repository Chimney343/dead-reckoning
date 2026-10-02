"""Scrapy settings: the politeness contract of rules 1, 2 and 6.

The 5 s delay is the site owner's condition (the robots.txt Crawl-delay).
Scrapy does not read Crawl-delay itself, so it is pinned here. The settings
contract test in tests/test_settings.py stops it being loosened by accident.
"""

from __future__ import annotations

import os
from pathlib import Path

from .ua import build_user_agent

BOT_NAME = "threedecks"
SPIDER_MODULES = ["threedecks.spiders"]
NEWSPIDER_MODULE = "threedecks.spiders"

REPO_ROOT = Path(__file__).resolve().parents[3]
DATA_DIR = Path(os.environ.get("THREEDECKS_DATA_DIR", REPO_ROOT / "data" / "threedecks"))

# The site, unless a test profile points the spiders at a local server.
THREEDECKS_BASE_URL = os.environ.get("THREEDECKS_BASE_URL", "https://threedecks.org").rstrip("/")

USER_AGENT = build_user_agent()
ROBOTSTXT_OBEY = True

# --- rate: the owner's condition ------------------------------------------
CONCURRENT_REQUESTS = 1
CONCURRENT_REQUESTS_PER_DOMAIN = 1
DOWNLOAD_DELAY = 5
RANDOMIZE_DOWNLOAD_DELAY = False
AUTOTHROTTLE_ENABLED = True
AUTOTHROTTLE_START_DELAY = 5
AUTOTHROTTLE_MAX_DELAY = 60
AUTOTHROTTLE_TARGET_CONCURRENCY = 0.5

# 403 and 429 are deliberately absent: those stop the crawl, never retry.
RETRY_TIMES = 2
RETRY_HTTP_CODES = [500, 502, 503, 504, 522, 524, 408]

# --- crash-safe HTTP cache (rule 6, design 4.3) ---------------------------
HTTPCACHE_ENABLED = True
HTTPCACHE_STORAGE = "threedecks.cache.SqliteCacheStorage"
HTTPCACHE_DIR = str(DATA_DIR)
HTTPCACHE_EXPIRATION_SECS = 0
HTTPCACHE_IGNORE_HTTP_CODES = [403, 429, 500, 502, 503, 504]

TELNETCONSOLE_ENABLED = False
REQUEST_FINGERPRINTER_IMPLEMENTATION = "2.7"
FEED_EXPORT_ENCODING = "utf-8"

ITEM_PIPELINES = {
    "threedecks.pipelines.ValidationPipeline": 100,
    "threedecks.pipelines.StatePipeline": 300,
}
DOWNLOADER_MIDDLEWARES = {"threedecks.middlewares.BlockDetectionMiddleware": 543}

# No default page cap. Smoke runs pass -s CLOSESPIDER_PAGECOUNT=25.
# No JOBDIR: resuming is handled by StateStore (design 4.3).
