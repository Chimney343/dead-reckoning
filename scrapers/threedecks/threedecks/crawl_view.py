"""A live view of a crawl for a terminal: a progress bar with an ETA at the bottom,
the latest Scrapy message on the line above it.

``scripts/crawl.py`` pipes every line of the crawl through :class:`CrawlView` and
still writes all of them to its log file. On the console, ordinary INFO lines
only replace the "latest message" line; warnings, errors, tracebacks and the
crawl driver's own lines scroll up above the two bars and stay.

The bar counts frontier rows settled (done, not found or failed for good)
against settled plus what is still pending or retryable. That is read from
``state.sqlite`` every few seconds, so it follows resumes and newly discovered
ids. The ETA is that remainder over the measured rate of the last ten minutes,
with time spent in a Cloudflare cool-off left out of the rate and the cool-off
still to come added on top. Until two minutes of progress exist, it uses the
site's pace (a page about every 7.5 s) instead.
"""

from __future__ import annotations

import re
import shutil
import sqlite3
import sys
import threading
import time
from collections import deque
from collections.abc import Callable
from pathlib import Path

LEVEL_LINE = re.compile(
    r"^\d{4}-\d{2}-\d{2} (\d{2}:\d{2}:\d{2})(?:,\d+)? \[[^\]]*\] "
    r"(DEBUG|INFO|WARNING|ERROR|CRITICAL): (.*)$",
    re.DOTALL,
)
QUIET_LEVELS = frozenset({"DEBUG", "INFO"})
# INFO lines worth keeping on screen: the closing stats and why a tier stopped.
KEEP_INFO = re.compile(
    r"Dumping Scrapy stats|Closing spider|Spider closed|target \d+ reached|"
    r"daily budget|crawl window|ship records stored"
)

POLL_SECS = 5.0
WINDOW_SECS = 600.0  # the rate comes from this much recent progress
MIN_SPAN_SECS = 120.0  # ... once at least this much is available
DEFAULT_RATE = 1 / 7.5  # pages per second: the 6 s delay plus about 1.5 s per response
MAX_RATE = 0.2  # the owner's floor is one request per 5 s, so nothing can beat this
MAX_ATTEMPTS = 3  # StateStore.pending_ids: an error row stops being retried here


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(max(seconds, 0)))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{days}d {clock}" if days else clock


class CrawlView:
    def __init__(
        self,
        data_dir: Path | str,
        *,
        out=None,
        disable: bool | None = None,
        clock: Callable[[], float] = time.monotonic,
        wall: Callable[[], float] = time.time,
        columns: Callable[[], int] | None = None,
    ) -> None:
        self.data_dir = Path(data_dir)
        self._out = out or sys.stdout
        self._disable = disable
        self._clock = clock
        self._wall = wall
        self._columns = columns or (lambda: shutil.get_terminal_size((100, 24)).columns)
        self._lock = threading.RLock()
        self._bar = None  # tqdm: the progress bar (bottom line)
        self._msg_bar = None  # tqdm: the latest message (the line above it)
        self._quiet = False  # whether the previous child line was a transient one
        self.last_message = ""
        self._heartbeat: Callable[[], dict | None] | None = None
        self._target = 0
        self._samples: deque[tuple[float, int]] = deque()
        self._paused = 0.0
        self._last_poll = 0.0
        self._tier = ""

    @classmethod
    def for_console(cls, data_dir: Path | str) -> CrawlView | None:
        """A view for the real terminal, or ``None`` when stdout is not one."""
        return cls(data_dir) if sys.stdout.isatty() else None

    # -- lines ---------------------------------------------------------------
    def show(self, text: str, kind: str = "plain") -> None:
        """One line of console output. ``kind`` is "child" for the crawl's own output."""
        line = text.rstrip("\r\n")
        with self._lock:
            if kind == "child":
                match = LEVEL_LINE.match(line)
                if match:
                    stamp, level, message = match.groups()
                    self._quiet = level in QUIET_LEVELS and not KEEP_INFO.search(message)
                    if self._quiet:
                        self._set_message(f"{stamp} {message}")
                        return
                elif self._quiet:
                    return  # the rest of a quiet multi-line message
            self._write(line)

    def _write(self, line: str) -> None:
        if self._bar is not None:
            from tqdm import tqdm

            tqdm.write(line, file=self._out)
        else:
            print(line, file=self._out, flush=True)

    def _set_message(self, message: str) -> None:
        message = " ".join(message.split())
        self.last_message = message
        if self._msg_bar is not None:
            width = max(self._columns() - 1, 20)
            self._msg_bar.set_description_str(message[:width])

    # -- tiers ---------------------------------------------------------------
    def start_tier(
        self, spider: str, ship_target: int = 0, heartbeat: Callable[[], dict | None] | None = None
    ) -> None:
        with self._lock:
            self._tier = spider
            self._target = ship_target
            self._heartbeat = heartbeat
            self._samples.clear()
            self._paused = 0.0
            self._last_poll = 0.0
            self._quiet = False
            if self._bar is None:
                from tqdm import tqdm

                self._msg_bar = tqdm(
                    total=0, position=0, leave=False, file=self._out, disable=self._disable,
                    bar_format="{desc}",
                )
                self._bar = tqdm(
                    total=0, position=1, leave=True, file=self._out, disable=self._disable,
                    bar_format="{desc} {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
                    "[{elapsed}]{postfix}",
                )
            self._bar.set_description_str(spider)
        self.tick(force=True)

    def end_tier(self) -> None:
        with self._lock:
            self._heartbeat = None
            self.tick(force=True)
            self._set_message("")

    def close(self) -> None:
        with self._lock:
            for bar in (self._msg_bar, self._bar):
                if bar is not None:
                    bar.close()
            self._msg_bar = self._bar = None

    # -- the bar -------------------------------------------------------------
    def tick(self, force: bool = False) -> None:
        """Refresh the bar from ``state.sqlite``; cheap to call every second."""
        with self._lock:
            if self._bar is None:
                return
            now = self._clock()
            if not force and now - self._last_poll < POLL_SECS:
                return
            elapsed = now - self._last_poll if self._last_poll else 0.0
            self._last_poll = now

            beat = self._heartbeat() if self._heartbeat else None
            cooloff_until = (beat or {}).get("cooloff_until")
            cooling = cooloff_until is not None and self._wall() < cooloff_until
            if cooling:
                self._paused += elapsed  # waiting out Cloudflare is not slowness

            state = self._read_state()
            if state is None:
                return
            settled, remaining, ships = state
            self._bar.total = settled + remaining
            self._bar.n = settled
            self._samples.append((now - self._paused, settled))
            while self._samples and self._samples[0][0] < now - self._paused - WINDOW_SECS:
                self._samples.popleft()

            rate = self._rate()
            parts = []
            if remaining == 0:
                parts.append("done")
            else:
                eta = None if rate is None else remaining / rate
                if eta is not None and cooling:
                    eta += cooloff_until - self._wall()
                parts.append(f"ETA {fmt_duration(eta)}")
            if rate is not None:
                parts.append(f"{rate * 60:.1f} pages/min")
            parts.append(f"{ships:,} ships")
            if cooling:
                until = time.strftime("%H:%M", time.localtime(cooloff_until))
                parts.append(f"cool-off until {until}")
            self._bar.set_postfix_str(" | ".join(parts))
            self._bar.refresh()

    def _rate(self) -> float | None:
        """Pages settled per second: recent, capped at the owner's rate; None if stuck."""
        if len(self._samples) >= 2:
            (t0, n0), (t1, n1) = self._samples[0], self._samples[-1]
            if t1 - t0 >= MIN_SPAN_SECS:
                if n1 <= n0:
                    return None
                return min((n1 - n0) / (t1 - t0), MAX_RATE)
        return DEFAULT_RATE

    def _read_state(self) -> tuple[int, int, int] | None:
        """(settled rows, rows still to fetch, ships stored), or None if unreadable."""
        path = self.data_dir / "state.sqlite"
        if not path.exists():
            return None
        try:
            conn = sqlite3.connect(str(path), timeout=1)
            try:
                rows = conn.execute(
                    "SELECT status, attempts >= ?, COUNT(*) FROM frontier GROUP BY 1, 2",
                    (MAX_ATTEMPTS,),
                ).fetchall()
                ships = conn.execute("SELECT COUNT(*) FROM ships").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            return None
        settled = remaining = 0
        for status, exhausted, count in rows:
            if status == "pending" or (status == "error" and not exhausted):
                remaining += count
            else:
                settled += count
        if self._target > 0:
            remaining = min(remaining, max(self._target - ships, 0))
        return settled, remaining, ships
