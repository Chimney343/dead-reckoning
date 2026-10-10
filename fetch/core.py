"""Download core: politeness, retries, streaming, resume and provenance.

This module deliberately has no knowledge of individual sources. A resolver
turns a manifest entry into one or more :class:`FileSpec` objects; the
functions here turn a spec into bytes on disk plus a provenance record.
"""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
import time
from dataclasses import dataclass, field
from email.utils import parsedate_to_datetime
from pathlib import Path

import httpx

PROJECT_URL = "https://github.com/Chimney343/dead-reckoning"
DEFAULT_UA = f"dead-reckoning-fetch/0.1 (+{PROJECT_URL})"
STREAM_CHUNK = 1024 * 256
RETRY_STATUSES = {408, 429, 500, 502, 503, 504, 522, 524}


class DownloadError(RuntimeError):
    """A request could not be completed after retries."""


class MissingContactError(RuntimeError):
    """DR_CONTACT is required for this source."""


# --- dotenv / user agent --------------------------------------------------


def load_dotenv(path: Path) -> dict[str, str]:
    """Parse a minimal ``KEY=value`` .env file. Quotes and blanks are handled."""
    values: dict[str, str] = {}
    path = Path(path)
    if not path.exists():
        return values
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"').strip("'")
        values[key.strip()] = value
    return values


CONTACT_KEYS = ("DR_CONTACT", "THREEDECKS_CONTACT")


def resolve_contact(
    environ: dict[str, str] | None = None,
    dotenv_path: Path | str = ".env",
) -> str | None:
    """Return the project contact for the User-Agent.

    ``DR_CONTACT`` is the fetch-facing name, but the older
    ``THREEDECKS_CONTACT`` is accepted too, so the single contact in the
    gitignored ``.env`` serves both the crawler and the fetcher. The process
    environment wins over the file.
    """
    environ = os.environ if environ is None else environ
    dotenv = load_dotenv(Path(dotenv_path))
    for source in (environ, dotenv):
        for key in CONTACT_KEYS:
            value = source.get(key)
            if value:
                return value
    return None


def build_user_agent(contact: str | None) -> str:
    if contact:
        return f"dead-reckoning-fetch/0.1 (+{contact})"
    return DEFAULT_UA


def require_contact(contact: str | None) -> str:
    if not contact:
        raise MissingContactError(
            "DR_CONTACT is not set. Wikimedia requires a contact in the "
            "User-Agent; set DR_CONTACT (or THREEDECKS_CONTACT) in the "
            "environment or in .env."
        )
    return contact


# --- rate limiting --------------------------------------------------------


class RateLimiter:
    """Serialise requests per host with a minimum gap between them."""

    def __init__(
        self,
        default_gap: float = 1.0,
        per_host: dict[str, float] | None = None,
        clock=time.monotonic,
        sleep=time.sleep,
    ) -> None:
        self.default_gap = default_gap
        self.per_host = per_host or {}
        self._clock = clock
        self._sleep = sleep
        self._last: dict[str, float] = {}

    def gap(self, host: str) -> float:
        return self.per_host.get(host, self.default_gap)

    def wait(self, host: str | None) -> None:
        host = host or ""
        gap = self.gap(host)
        if gap <= 0:
            return
        last = self._last.get(host)
        if last is not None:
            remaining = gap - (self._clock() - last)
            if remaining > 0:
                self._sleep(remaining)
        self._last[host] = self._clock()


def _retry_after(response: httpx.Response) -> float | None:
    value = response.headers.get("Retry-After")
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        try:
            delta = parsedate_to_datetime(value).timestamp() - time.time()
        except (TypeError, ValueError):
            return None
        return max(0.0, delta)


# --- checksums / provenance ----------------------------------------------


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(STREAM_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_provenance(path: Path) -> dict:
    path = Path(path)
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def write_provenance(path: Path, data: dict) -> None:
    """Write provenance JSON atomically."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".prov-", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def utcnow() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


# --- HTTP client ----------------------------------------------------------


@dataclass
class FileSpec:
    """A resolved download target.

    ``urls`` usually holds one URL. For paged APIs it can hold several, and
    ``merge`` describes how to combine them (currently only ``"geojson"``).
    ``meta`` holds resolver inputs that belong in the provenance record.
    """

    urls: list[str]
    filename: str
    merge: str | None = None
    meta: dict = field(default_factory=dict)


@dataclass
class DownloadResult:
    url: str
    final_url: str
    filename: str
    path: Path
    status: int
    bytes: int
    sha256: str
    etag: str | None
    last_modified: str | None
    skipped: bool
    fetched_at: str

    def as_provenance(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "bytes": self.bytes,
            "sha256": self.sha256,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "fetched_at": self.fetched_at,
        }


class HttpClient:
    def __init__(
        self,
        contact: str | None = None,
        *,
        client: httpx.Client | None = None,
        limiter: RateLimiter | None = None,
        max_attempts: int = 5,
        timeout: float = 60.0,
        backoff_base: float = 0.5,
        user_agent: str | None = None,
    ) -> None:
        self.contact = contact
        self.user_agent = user_agent or build_user_agent(contact)
        self.max_attempts = max_attempts
        self.backoff_base = backoff_base
        self.limiter = limiter or RateLimiter()
        self._owns_client = client is None
        self._client = client or httpx.Client(
            timeout=timeout,
            follow_redirects=True,
            headers={"User-Agent": self.user_agent},
        )

    # -- lifecycle
    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def __enter__(self) -> HttpClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # -- retry helpers
    def _backoff(self, attempt: int) -> float:
        return self.backoff_base * (2 ** (attempt - 1))

    def _wait(self, url: str) -> None:
        self.limiter.wait(httpx.URL(url).host)

    def get(self, url: str, **kwargs) -> httpx.Response:
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> httpx.Response:
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> httpx.Response:
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self._wait(url)
                response = self._client.request(method, url, **kwargs)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                time.sleep(self._backoff(attempt))
                continue
            if response.status_code in RETRY_STATUSES:
                if attempt >= self.max_attempts:
                    response.close()
                    raise DownloadError(
                        f"{method} {url} failed with {response.status_code} "
                        f"after {attempt} attempts"
                    )
                delay = _retry_after(response)
                response.close()
                time.sleep(delay if delay is not None else self._backoff(attempt))
                continue
            return response
        raise DownloadError(
            f"{method} {url} failed after {self.max_attempts} attempts: {last_exc}"
        )

    def open(self, method: str, url: str, **kwargs) -> httpx.Response:
        """Send a request with ``stream=True`` and return the open response."""
        request = self._client.build_request(method, url, **kwargs)
        last_exc: Exception | None = None
        for attempt in range(1, self.max_attempts + 1):
            try:
                self.limiter.wait(request.url.host)
                response = self._client.send(request, stream=True)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt >= self.max_attempts:
                    break
                time.sleep(self._backoff(attempt))
                continue
            if response.status_code in RETRY_STATUSES:
                if attempt >= self.max_attempts:
                    response.close()
                    raise DownloadError(
                        f"{method} {url} failed with {response.status_code} "
                        f"after {attempt} attempts"
                    )
                delay = _retry_after(response)
                response.close()
                time.sleep(delay if delay is not None else self._backoff(attempt))
                continue
            return response
        raise DownloadError(
            f"{method} {url} failed after {self.max_attempts} attempts: {last_exc}"
        )


# --- download -------------------------------------------------------------


class NullReporter:
    """Receives download progress events and ignores them.

    ``fetch.progress.ProgressReporter`` implements the same methods.
    """

    def entry_start(self, entry) -> None: ...

    def file_start(self, filename: str, total: int | None, resume_from: int = 0) -> None: ...

    def advance(self, n: int) -> None: ...

    def file_end(self) -> None: ...

    def entry_done(self) -> None: ...

    def write(self, message: str) -> None:
        print(message)

    def close(self) -> None: ...


def _content_length(response: httpx.Response) -> int | None:
    value = response.headers.get("content-length")
    if value is None:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _skipped_result(
    url: str, spec: FileSpec, dest: Path, prior: dict, status: int
) -> DownloadResult:
    return DownloadResult(
        url=url,
        final_url=prior.get("final_url", url),
        filename=spec.filename,
        path=dest,
        status=prior.get("status", status),
        bytes=dest.stat().st_size if dest.exists() else prior.get("bytes", 0),
        sha256=prior.get("sha256") or (sha256_file(dest) if dest.exists() else ""),
        etag=prior.get("etag"),
        last_modified=prior.get("last_modified"),
        skipped=True,
        fetched_at=prior.get("fetched_at", utcnow()),
    )


def _download_one(
    client: HttpClient,
    spec: FileSpec,
    dest_dir: Path,
    prior: dict,
    force: bool,
    reporter: NullReporter,
) -> DownloadResult:
    url = spec.urls[0]
    dest = dest_dir / spec.filename
    part = dest.with_name(dest.name + ".part")

    # 1. Skip if unchanged.
    if dest.exists() and not force:
        headers: dict[str, str] = {}
        if prior.get("etag"):
            headers["If-None-Match"] = prior["etag"]
        if prior.get("last_modified"):
            headers["If-Modified-Since"] = prior["last_modified"]
        response = client.open("GET", url, headers=headers)
        if response.status_code == 304:
            response.close()
            return _skipped_result(url, spec, dest, prior, 304)
        total = _content_length(response)
        local = dest.stat().st_size
        if total is not None and total == local and prior.get("bytes") == total:
            response.close()
            return _skipped_result(url, spec, dest, prior, response.status_code)
        response_etag = response.headers.get("ETag")
        response_lm = response.headers.get("Last-Modified")
        if prior.get("etag") and response_etag == prior["etag"]:
            response.close()
            return _skipped_result(url, spec, dest, prior, response.status_code)
        if prior.get("last_modified") and response_lm == prior["last_modified"]:
            response.close()
            return _skipped_result(url, spec, dest, prior, response.status_code)
        has_validators = bool(prior.get("etag") or prior.get("last_modified"))
        if (
            total is None
            and not has_validators
            and prior.get("bytes") == local
            and local > 0
        ):
            response.close()
            return _skipped_result(url, spec, dest, prior, response.status_code)
        response.close()

    # 2. Resume a partial file when there is no complete file to replace.
    resume_from = 0
    if not force and not dest.exists() and part.exists():
        resume_from = part.stat().st_size
    if force and part.exists():
        part.unlink()

    headers = {}
    if resume_from:
        headers["Range"] = f"bytes={resume_from}-"
    response = client.open("GET", url, headers=headers)
    if resume_from and response.status_code != 206:
        response.close()
        part.unlink(missing_ok=True)
        resume_from = 0
        response = client.open("GET", url)

    final_url = str(response.url)
    etag = response.headers.get("ETag")
    last_modified = response.headers.get("Last-Modified")
    status = response.status_code

    length = _content_length(response)
    reporter.file_start(
        spec.filename, None if length is None else resume_from + length, resume_from
    )
    mode = "ab" if resume_from else "wb"
    try:
        with open(part, mode) as fh:
            for chunk in response.iter_bytes(STREAM_CHUNK):
                fh.write(chunk)
                reporter.advance(len(chunk))
    finally:
        reporter.file_end()
        response.close()

    if dest.exists():
        dest.unlink()
    part.replace(dest)

    size = dest.stat().st_size
    return DownloadResult(
        url=url,
        final_url=final_url,
        filename=spec.filename,
        path=dest,
        status=status,
        bytes=size,
        sha256=sha256_file(dest),
        etag=etag,
        last_modified=last_modified,
        skipped=False,
        fetched_at=utcnow(),
    )


def _download_geojson(
    client: HttpClient,
    spec: FileSpec,
    dest_dir: Path,
    prior: dict,
    force: bool,
) -> DownloadResult:
    dest = dest_dir / spec.filename
    if dest.exists() and not force and prior.get("bytes") == dest.stat().st_size:
        return _skipped_result(spec.urls[0], spec, dest, prior, 304)

    features: list[dict] = []
    status = 200
    final_url = spec.urls[0]
    for url in spec.urls:
        response = client.get(url)
        status = response.status_code
        final_url = str(response.url)
        payload = response.json()
        features.extend(payload.get("features", []))

    collection = {"type": "FeatureCollection", "features": features}
    part = dest.with_name(dest.name + ".part")
    part.write_text(json.dumps(collection), encoding="utf-8")
    if dest.exists():
        dest.unlink()
    part.replace(dest)
    size = dest.stat().st_size
    return DownloadResult(
        url=spec.urls[0],
        final_url=final_url,
        filename=spec.filename,
        path=dest,
        status=status,
        bytes=size,
        sha256=sha256_file(dest),
        etag=None,
        last_modified=None,
        skipped=False,
        fetched_at=utcnow(),
    )


def download_file(
    client: HttpClient,
    spec: FileSpec,
    dest_dir: Path | str,
    prior: dict | None = None,
    force: bool = False,
    reporter: NullReporter | None = None,
) -> DownloadResult:
    dest_dir = Path(dest_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    prior = prior or {}
    if spec.merge == "geojson":
        return _download_geojson(client, spec, dest_dir, prior, force)
    return _download_one(client, spec, dest_dir, prior, force, reporter or NullReporter())
