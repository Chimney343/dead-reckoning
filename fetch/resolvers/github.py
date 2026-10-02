"""GitHub: prefer raw/codeload URLs over the rate-limited API."""

from __future__ import annotations

import re
from urllib.parse import urlparse

from ..core import FileSpec
from ..manifest import Entry
from . import safe_filename

REPO_RE = re.compile(r"^https?://github\.com/([^/]+)/([^/]+?)(?:\.git)?/?$")


def resolve(entry: Entry, client) -> list[FileSpec]:
    url = entry.url
    repo = None
    filename = entry.filename
    if "/raw/" not in url:
        match = REPO_RE.match(url)
        if match:
            repo = f"{match.group(1)}/{match.group(2)}"
            url = f"https://codeload.github.com/{repo}/zip/HEAD"
            filename = filename or f"{match.group(2)}-HEAD.zip"
    filename = filename or safe_filename(urlparse(url).path)
    return [FileSpec(urls=[url], filename=filename, meta={"repo": repo, "source": entry.url})]
