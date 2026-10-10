"""Progress bars and an ETA for ``python -m fetch get``.

Two bars: the outer one counts sources, the inner one follows the file being
streamed (tqdm's own rate and ETA are right for a single file). The outer ETA
is ours, because the time left is not just bytes over rate: most of a run is
rate-limit gaps, resolver calls and the up-to-date check on each file. So the
model learns two things as the run goes on:

* the streaming rate: bytes received over seconds spent receiving them;
* the per-source overhead: wall time per source minus its streaming time,
  kept separately for plain downloads and harvesters (paged APIs), whose
  cost is requests, not bytes.

ETA = bytes still to come / rate + sources still to start * their overhead.
Bytes still to come are the manifest's ``approx_bytes``; a source that was
already downloaded counts as zero, because it will most likely be skipped.
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from tqdm import tqdm

from . import core, harvesters, manifest

FALLBACK_BYTES = 1_000_000  # a source with no approx_bytes, when nothing else is known
DEFAULT_OVERHEAD = {"file": 3.0, "harvest": 30.0}  # seconds per source, until measured
MIN_RATE_BYTES = 256 * 1024  # stream at least this much, for this long, before
MIN_RATE_SECS = 2.0  # trusting a rate
REFRESH_SECS = 0.25


@dataclass
class Plan:
    """What a run expects of one source."""

    id: str
    kind: str  # "file" or "harvest"
    weight: int  # expected bytes to download; 0 when it will most likely be skipped


def fmt_duration(seconds: float | None) -> str:
    if seconds is None:
        return "?"
    seconds = int(round(seconds))
    days, rest = divmod(seconds, 86400)
    hours, rest = divmod(rest, 3600)
    minutes, secs = divmod(rest, 60)
    clock = f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{days}d {clock}" if days else clock


def fmt_rate(bytes_per_sec: float | None) -> str:
    if bytes_per_sec is None:
        return "? B/s"
    value = float(bytes_per_sec)
    for unit in ("B", "KB", "MB", "GB"):
        if value < 1024 or unit == "GB":
            return f"{value:.1f} {unit}/s"
        value /= 1024
    return f"{value:.1f} GB/s"


def make_plans(
    entries: list[manifest.Entry], root: Path | None = None, *, force: bool = False
) -> list[Plan]:
    """Expected work per source, in run order."""
    known = [e.approx_bytes for e in entries if e.approx_bytes > 0]
    fallback = int(statistics.median(known)) if known else FALLBACK_BYTES
    plans = []
    for entry in entries:
        if entry.resolver in harvesters.HARVESTERS:
            plans.append(Plan(entry.id, "harvest", 0))
            continue
        weight = entry.approx_bytes or fallback
        if not force and _already_downloaded(entry, root):
            weight = 0
        plans.append(Plan(entry.id, "file", weight))
    return plans


def _already_downloaded(entry: manifest.Entry, root: Path | None) -> bool:
    dest_dir = manifest.entry_dir(entry, root)
    files = core.read_provenance(dest_dir / "_provenance.json").get("files", {})
    return bool(files) and all((dest_dir / name).exists() for name in files)


class EtaModel:
    """Learns the streaming rate and per-source overhead; estimates time left."""

    def __init__(self, plans: list[Plan], clock: Callable[[], float] = time.monotonic) -> None:
        self.clock = clock
        self.pending = list(plans)
        self.current: Plan | None = None
        self.started = clock()
        self._entry_t0 = 0.0
        self._entry_stream = 0.0
        self._entry_bytes = 0
        self._entry_resumed = 0
        self._file_remaining: int | None = None
        self._file_t0: float | None = None
        self.stream_bytes = 0
        self.stream_secs = 0.0
        self._overhead = {kind: [0.0, 0] for kind in DEFAULT_OVERHEAD}
        self.done = 0
        self.total = len(plans)

    # -- events
    def start_entry(self, entry_id: str) -> None:
        index = next((i for i, p in enumerate(self.pending) if p.id == entry_id), None)
        self.current = self.pending.pop(index) if index is not None else Plan(entry_id, "file", 0)
        self._entry_t0 = self.clock()
        self._entry_stream = 0.0
        self._entry_bytes = 0
        self._entry_resumed = 0
        self._file_remaining = None

    def file_start(self, total: int | None, resume_from: int = 0) -> None:
        self._file_t0 = self.clock()
        self._entry_resumed += resume_from
        self._file_remaining = None if total is None else max(total - resume_from, 0)

    def advance(self, n: int) -> None:
        self._entry_bytes += n
        self.stream_bytes += n
        if self._file_remaining is not None:
            self._file_remaining = max(self._file_remaining - n, 0)

    def file_end(self) -> None:
        if self._file_t0 is not None:
            secs = self.clock() - self._file_t0
            self._entry_stream += secs
            self.stream_secs += secs
            self._file_t0 = None
        self._file_remaining = None

    def finish_entry(self) -> None:
        if self.current is None:
            return
        wall = self.clock() - self._entry_t0
        bucket = self._overhead[self.current.kind]
        bucket[0] += max(wall - self._entry_stream, 0.0)
        bucket[1] += 1
        self.done += 1
        self.current = None

    # -- estimates
    def streaming_secs(self) -> float:
        """Seconds spent receiving bytes, the file in flight included."""
        live = self.clock() - self._file_t0 if self._file_t0 is not None else 0.0
        return self.stream_secs + live

    def byte_rate(self) -> float | None:
        secs = self.streaming_secs()
        if self.stream_bytes < MIN_RATE_BYTES or secs < MIN_RATE_SECS:
            return None
        return self.stream_bytes / secs

    def overhead(self, kind: str) -> float:
        seconds, count = self._overhead[kind]
        return seconds / count if count else DEFAULT_OVERHEAD[kind]

    def remaining_bytes(self) -> int:
        remaining = sum(p.weight for p in self.pending)
        if self.current is not None:
            left = max(self.current.weight - self._entry_resumed - self._entry_bytes, 0)
            if self._file_remaining is not None:
                left = max(left, self._file_remaining)
            remaining += left
        return remaining

    def eta_secs(self) -> float | None:
        """Seconds left, or ``None`` while there are bytes to fetch but no rate yet."""
        secs = sum(
            count * self.overhead(kind)
            for kind, count in Counter(p.kind for p in self.pending).items()
        )
        remaining = self.remaining_bytes()
        if remaining > 0:
            rate = self.byte_rate()
            if rate is None:
                return None
            secs += remaining / rate
        return secs


class ProgressReporter:
    """Drives the two tqdm bars from the events ``core`` and ``run`` emit.

    tqdm switches itself off when stderr is not a terminal, so redirected
    output stays clean; the model keeps running either way.
    """

    def __init__(
        self,
        entries: list[manifest.Entry],
        root: Path | None = None,
        *,
        force: bool = False,
        clock: Callable[[], float] = time.monotonic,
        disable: bool | None = None,
    ) -> None:
        self.model = EtaModel(make_plans(entries, root, force=force), clock)
        self._clock = clock
        self._disable = disable
        self._refreshed = 0.0
        self._label = ""
        self._file_bar: tqdm | None = None
        self._bar = tqdm(
            total=len(entries),
            unit="src",
            desc="fetch",
            position=0,
            leave=True,
            disable=disable,
            bar_format="{l_bar}{bar}| {n_fmt}/{total_fmt} [{elapsed}]{postfix}",
        )
        self._update_postfix()

    # -- events (the core.NullReporter interface)
    def entry_start(self, entry: manifest.Entry) -> None:
        self.model.start_entry(entry.id)
        self._label = entry.id
        self._update_postfix()

    def file_start(self, filename: str, total: int | None, resume_from: int = 0) -> None:
        self.model.file_start(total, resume_from)
        self._close_file_bar()
        self._file_bar = tqdm(
            total=total,
            initial=resume_from if total is not None else 0,
            unit="B",
            unit_scale=True,
            unit_divisor=1024,
            desc=f"  {filename[:40]}",
            position=1,
            leave=False,
            disable=self._disable,
        )

    def advance(self, n: int) -> None:
        self.model.advance(n)
        if self._file_bar is not None:
            self._file_bar.update(n)
        now = self._clock()
        if now - self._refreshed >= REFRESH_SECS:
            self._refreshed = now
            self._update_postfix()

    def file_end(self) -> None:
        self.model.file_end()
        self._close_file_bar()

    def entry_done(self) -> None:
        self.model.finish_entry()
        self._bar.update(1)
        self._label = ""
        self._update_postfix()

    # -- output
    def write(self, message: str) -> None:
        tqdm.write(message)

    def close(self) -> None:
        self._close_file_bar()
        self._update_postfix()
        self._bar.close()

    def _close_file_bar(self) -> None:
        if self._file_bar is not None:
            self._file_bar.close()
            self._file_bar = None

    def _update_postfix(self) -> None:
        running = bool(self.model.pending or self.model.current)
        parts = [
            f"ETA {fmt_duration(self.model.eta_secs())}" if running else "done",
            fmt_rate(self.model.byte_rate()),
        ]
        if self._label:
            parts.append(self._label)
        self._bar.set_postfix_str(" | ".join(parts), refresh=True)
