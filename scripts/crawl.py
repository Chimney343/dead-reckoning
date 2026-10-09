"""Crawl Three Decks tier by tier until the database holds N ship records.

    uv run python scripts/crawl.py [--ships 5000 | --more 1000]
                                   [--tiers captures,ships_by_nation,ships_all] [--rerun]
                                   [--allow-sleep] [-s KEY=VALUE ...]

Runs Tier A (``captures``: Spanish ships taken by Britain), then Tier B
(``ships_by_nation``: every Spanish ship), then Tier C (``ships_all``: every
ship id), each as a normal ``scrapy crawl``, so the 5 s rate, the Cloudflare
cool-offs and resuming all apply. A tier ends when its list is exhausted or the
database holds ``--ships`` ship records (``THREEDECKS_SHIP_TARGET``). A tier
whose last run finished is skipped (``--rerun`` replays it from the cache).

``--ships`` is a total, so rerunning the same command continues to the same
target. ``--more N`` sets the target to N above what is stored when the run
starts, for crawling in fixed-size sessions.

While it runs, it keeps Windows awake (the screen stays on; ``--allow-sleep``
turns this off), writes everything to ``data/threedecks/logs/``, and watches the
crawl's heartbeat: a crawl with no new response for 20 minutes outside a
Cloudflare cool-off is restarted (twice at most). If the network goes down, the
tier closes without charging attempts and is retried after 5, 10, then 20 minutes.

The chain stops at the target, on a ``blocked`` close (rule 5: do not move on
to the next tier against a block), on Ctrl+C, or on any other unexpected close.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import logging
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

from threedecks.extensions import HEARTBEAT_FILE, SHIP_TARGET_REASON
from threedecks.lock import CrawlLock, CrawlLockHeld
from threedecks.politeness import parse_override, refusal_message, refused_overrides
from threedecks.settings import (
    DATA_DIR,
    TARGETED_CLOSE_REASON,
    THREEDECKS_BASE_URL,
    THREEDECKS_INCOMPLETE_LIMIT,
)
from threedecks.state import StateStore, utc_iso
from threedecks.ua import MISSING_CONTACT_HELP, contact

SCRAPY_DIR = Path(__file__).resolve().parents[1] / "scrapers" / "threedecks"
TIERS = ("captures", "ships_by_nation", "ships_all")
# Non-ship crawlers (actions, fleets) run under this driver too, for the lock,
# watchdog and logs, but are opt-in: each Part B plan appends its spider's name.
# The default stays TIERS, so crawl_all.py and a bare crawl.py never run them.
EXTRA_TIERS: tuple[str, ...] = ("actions", "fleets")

WATCH_SECS = 30  # how often the watchdog looks at the heartbeat
SUSPEND_GAP_SECS = 120  # a longer gap between looks means the PC was asleep
STALL_SECS = 20 * 60  # no new response for this long, outside a cool-off, is a stall
MAX_RESTARTS = 2  # per tier and session
PAUSE_SECS = 10  # before each tier starts: a new process sends robots.txt at once
NETWORK_WAITS_MIN = "5,10,20"  # minutes before each retry of a tier that lost the network

# Windows SetThreadExecutionState flags.
ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
ES_DISPLAY_REQUIRED = 0x00000002  # Modern Standby starts when the screen idles off

PENDING_REBOOT_KEYS = (
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
)


class Log:
    """Print to the console and append to the session's log file."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._file = path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def write(self, text: str) -> None:
        with self._lock:
            sys.stdout.write(text)
            sys.stdout.flush()
            self._file.write(text)
            self._file.flush()

    def say(self, message: str) -> None:
        self.write(f"[crawl {time.strftime('%H:%M:%S')}] {message}\n")

    def tee(self, stream) -> None:
        """Copy a child's output, line by line, until it closes."""
        for raw in iter(stream.readline, b""):
            self.write(raw.decode("utf-8", "replace").replace("\r\n", "\n"))

    def close(self) -> None:
        self._file.close()


class Watchdog:
    """Reads the crawl's heartbeat; says when the PC slept or the crawl stalled.

    It only ever reports a stall after it has seen the crawl's heartbeat: if
    the heartbeat never arrives, the watchdog is what is broken, and a healthy
    crawl must not be killed for it (it reports "no_heartbeat" once instead).
    """

    def __init__(self, now: float, stall_secs: float = STALL_SECS) -> None:
        self.stall_secs = stall_secs
        self.started = now
        self.last_look = now
        self.last_progress = now
        self.responses = None
        self.seen_beat = False
        self.warned = False

    def look(self, now: float, heartbeat: dict | None) -> tuple[str, float] | None:
        gap = now - self.last_look
        self.last_look = now
        if gap > SUSPEND_GAP_SECS:
            self.last_progress = now  # grace: after waking, the crawl carries on by itself
            return "suspended", gap
        beat = heartbeat or {}
        if heartbeat:
            self.seen_beat = True
        elif not self.seen_beat:
            if not self.warned and now - self.started > 5 * 60:
                self.warned = True
                return "no_heartbeat", now - self.started
            return None
        if beat.get("responses") is not None and beat["responses"] != self.responses:
            self.responses = beat["responses"]
            self.last_progress = now
        cooloff_until = beat.get("cooloff_until")
        if cooloff_until is not None and now < cooloff_until + 120:
            self.last_progress = now  # waiting out Cloudflare is not a stall
        if now - self.last_progress > self.stall_secs:
            return "stalled", now - self.last_progress
        return None


@dataclass
class TierResult:
    code: int | None
    interrupted: bool = False
    stalled: bool = False


@contextlib.contextmanager
def keep_awake(enabled: bool):
    """Ask Windows not to sleep (nor blank the screen) while the crawl runs."""
    if not enabled or sys.platform != "win32":
        yield False
        return
    import ctypes

    kernel32 = ctypes.windll.kernel32
    flags = ES_CONTINUOUS | ES_SYSTEM_REQUIRED | ES_DISPLAY_REQUIRED
    ok = kernel32.SetThreadExecutionState(flags) != 0
    try:
        yield ok
    finally:
        kernel32.SetThreadExecutionState(ES_CONTINUOUS)


def pending_reboot() -> bool:
    """Whether Windows has an update waiting to restart the PC."""
    if sys.platform != "win32":
        return False
    import winreg

    for key in PENDING_REBOOT_KEYS:
        try:
            winreg.CloseKey(winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, key))
            return True
        except OSError:
            continue
    return False


# PowerShell 5.1 WinRT toast, shown under the Windows PowerShell AppUserModelID
# (toasts from an unregistered AppUserModelID do not appear).
_TOAST_PS = "\n".join(
    [
        "$ErrorActionPreference = 'SilentlyContinue'",
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, "
        "ContentType = WindowsRuntime] > $null",
        "[Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, "
        "ContentType = WindowsRuntime] > $null",
        "$template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent("
        "[Windows.UI.Notifications.ToastTemplateType]::ToastText02)",
        "$texts = $template.GetElementsByTagName('text')",
        "$texts.Item(0).AppendChild($template.CreateTextNode('__TITLE__')) > $null",
        "$texts.Item(1).AppendChild($template.CreateTextNode('__BODY__')) > $null",
        "$toast = [Windows.UI.Notifications.ToastNotification]::new($template)",
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("
        "'__APPID__').Show($toast)",
    ]
)
TOAST_APP_ID = r"{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\WindowsPowerShell\v1.0\powershell.exe"


def notify(title: str, body: str, log: Log) -> None:
    """Show a desktop toast at the end of a failed run; best-effort, never fatal.

    An unattended run that stops (blocked, stalled, network down) should be
    visible away from the console. The line ``log.say`` writes is always there;
    the toast itself may fail silently.
    """
    log.say(f"notification: {title}: {body}")
    if sys.platform != "win32":
        return
    script = (
        _TOAST_PS.replace("__TITLE__", title.replace("'", "''"))
        .replace("__BODY__", body.replace("'", "''"))
        .replace("__APPID__", TOAST_APP_ID)
    )
    try:
        subprocess.run(
            ["powershell", "-NoProfile", "-Command", script],
            creationflags=subprocess.CREATE_NO_WINDOW,
            capture_output=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        logging.getLogger(__name__).debug("toast notification failed", exc_info=True)


def ship_count(data_dir: Path) -> int:
    with StateStore(data_dir / "state.sqlite") as store:
        return store.ship_count()


def last_run(data_dir: Path, spider: str) -> dict | None:
    conn = sqlite3.connect(str(data_dir / "state.sqlite"))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT * FROM runs WHERE spider = ? ORDER BY run_id DESC LIMIT 1", (spider,)
        ).fetchone()
    finally:
        conn.close()
    return dict(row) if row else None


def read_heartbeat(data_dir: Path, token: str) -> dict | None:
    """This tier's heartbeat. Matched by a token, not a process id: on Windows a
    virtual environment's python.exe is a launcher, and the crawl runs in a child
    process with another id."""
    try:
        beat = json.loads((data_dir / HEARTBEAT_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return beat if beat.get("token") == token else None  # not a previous tier's


# --- daily budget and crawl window (opt-in via --daily-pages / --window) ------

MIN_WINDOW_MINUTES = 10


def parse_hhmm(text: str) -> int:
    """``HH:MM`` to minutes since local midnight."""
    match = re.fullmatch(r"(\d{1,2}):(\d{2})", text.strip())
    if not match:
        raise ValueError(f"expected HH:MM, got {text!r}")
    hours, minutes = int(match.group(1)), int(match.group(2))
    if hours > 23 or minutes > 59:
        raise ValueError(f"expected HH:MM, got {text!r}")
    return hours * 60 + minutes


def parse_window(text: str) -> tuple[int, int]:
    """``HH:MM-HH:MM`` to (start, end) minutes since midnight; overnight wraps."""
    parts = text.strip().split("-")
    if len(parts) != 2:
        raise ValueError(f"expected HH:MM-HH:MM, got {text!r}")
    start, end = parse_hhmm(parts[0]), parse_hhmm(parts[1])
    if (end - start) % (24 * 60) < MIN_WINDOW_MINUTES:
        raise ValueError(f"window must span at least {MIN_WINDOW_MINUTES} min: {text!r}")
    return start, end


def _local_boundary(now: float, minutes: int, *, forward: bool) -> float:
    """Epoch of the local HH:MM boundary: the latest before, or the next after, now."""
    hours, mins = divmod(minutes, 60)
    local = time.localtime(now)
    boundary = time.mktime((local.tm_year, local.tm_mon, local.tm_mday, hours, mins, 0, 0, 0, -1))
    if forward and boundary <= now:
        boundary = time.mktime(
            (local.tm_year, local.tm_mon, local.tm_mday + 1, hours, mins, 0, 0, 0, -1)
        )
    elif not forward and boundary > now:
        boundary = time.mktime(
            (local.tm_year, local.tm_mon, local.tm_mday - 1, hours, mins, 0, 0, 0, -1)
        )
    return boundary


def day_start_epoch(now: float, day_start: str) -> float:
    """The current local day-start boundary (the latest ``HH:MM`` at or before now)."""
    return _local_boundary(now, parse_hhmm(day_start), forward=False)


def next_day_start(now: float, day_start: str) -> float:
    """The next local ``HH:MM`` boundary strictly after ``now``."""
    return _local_boundary(now, parse_hhmm(day_start), forward=True)


def window_wait_seconds(now: float, window: tuple[int, int]) -> float:
    """0 while ``now`` is inside the window; otherwise seconds until the next start."""
    start, end = window
    local = time.localtime(now)
    minutes = local.tm_hour * 60 + local.tm_min
    inside = start <= minutes < end if start <= end else minutes >= start or minutes < end
    if inside:
        return 0.0
    return _local_boundary(now, start, forward=True) - now


def window_end_epoch(now: float, window: tuple[int, int]) -> float:
    """Epoch of the current window's end; only meaningful while inside the window."""
    return _local_boundary(now, window[1], forward=True)


def pages_today(data_dir: Path, day_start: str, now: float | None = None) -> int:
    """Live pages in the runs that started since the current local day-start boundary."""
    boundary = utc_iso(day_start_epoch(time.time() if now is None else now, day_start))
    conn = sqlite3.connect(str(data_dir / "state.sqlite"))
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(pages_fetched), 0) FROM runs WHERE started_at >= ?",
            (boundary,),
        ).fetchone()
    finally:
        conn.close()
    return int(row[0])


def tier_command(
    spider: str,
    target: int | None,
    overrides: dict[str, str],
    *,
    token: str | None = None,
    daily_pages: int = 0,
    stop_at: float = 0.0,
) -> list[str]:
    """The ``scrapy crawl`` argv for one tier.

    ``target`` is the ship target. Ship tiers always carry it; an extra tier
    (actions, fleets) passes ``None`` and gets no ``THREEDECKS_SHIP_TARGET``.
    """
    command = [
        sys.executable, "-m", "scrapy", "crawl", spider,
        "-s", "LOG_LEVEL=INFO",
    ]
    if target is not None:
        command += ["-s", f"THREEDECKS_SHIP_TARGET={target}"]
    command += ["-s", f"THREEDECKS_RUN_TOKEN={token or uuid.uuid4().hex}"]
    # The budget and the window are set here, not through user -s overrides:
    # they are per-tier instructions, not politeness settings to inspect.
    if daily_pages > 0:
        command += ["-s", f"THREEDECKS_DAILY_PAGES={daily_pages}"]
    if stop_at > 0:
        command += ["-s", f"THREEDECKS_STOP_AT={stop_at}"]
    for key, value in overrides.items():
        command += ["-s", f"{key}={value}"]
    return command


def run_tier(spider: str, target: int | None, overrides: dict[str, str], data_dir: Path,
             log: Log, stall_secs: float = STALL_SECS, watch_secs: float = WATCH_SECS,
             daily_pages: int = 0, stop_at: float = 0.0) -> TierResult:
    """Run one ``scrapy crawl`` under the watchdog."""
    token = uuid.uuid4().hex
    command = tier_command(
        spider, target, overrides,
        token=token, daily_pages=daily_pages, stop_at=stop_at,
    )
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(
        command, cwd=SCRAPY_DIR, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT
    )
    copier = threading.Thread(target=log.tee, args=(process.stdout,), daemon=True)
    copier.start()
    result = TierResult(code=None)
    watchdog = Watchdog(time.time(), stall_secs)
    next_look = time.time() + watch_secs
    while result.code is None:
        try:
            result.code = process.wait(timeout=1)
            break
        except subprocess.TimeoutExpired:
            pass
        except KeyboardInterrupt:
            # Ctrl+C reaches Scrapy too: it finishes the page in flight and saves.
            result.interrupted = True
            log.say("stopping: Scrapy is finishing the page in flight ...")
            continue
        now = time.time()
        if now < next_look or result.interrupted:
            continue
        next_look = now + watch_secs
        event = watchdog.look(now, read_heartbeat(data_dir, token))
        if event and event[0] == "no_heartbeat":
            log.say("warning: no heartbeat from the crawl, so the stall watchdog is off "
                    "for this tier; the crawl itself carries on")
        elif event and event[0] == "suspended":
            log.say(f"the PC was asleep or suspended for {event[1] / 60:.0f} min; carrying on")
        elif event and event[0] == "stalled":
            log.say(f"no new response for {event[1] / 60:.0f} min outside a cool-off: "
                    f"stopping {spider} (a hard stop loses at most the page in flight)")
            process.kill()
            result.code = process.wait()
            result.stalled = True
    copier.join(timeout=5)
    return result


def tier_finished(data_dir: Path, spider: str) -> str | None:
    """When the tier's last run finished its list, or None."""
    run = last_run(data_dir, spider)
    return run["finished_at"] if run and run["close_reason"] == "finished" else None


def wait_minutes(minutes: float, log: Log) -> bool:
    """Sleep, waking each second for Ctrl+C. False if interrupted."""
    deadline = time.time() + minutes * 60
    try:
        while time.time() < deadline:
            time.sleep(min(1.0, max(0.0, deadline - time.time())))
    except KeyboardInterrupt:
        log.say("stopped while waiting")
        return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    target = parser.add_mutually_exclusive_group()
    target.add_argument("--ships", type=int, default=5000, help="total ship records to reach")
    target.add_argument("--more", type=int, help="ship records to add in this run")
    parser.add_argument(
        "--tiers", default=",".join(TIERS), help="spiders to run, in order (comma-separated)"
    )
    parser.add_argument("--rerun", action="store_true", help="replay tiers that finished")
    parser.add_argument("--allow-sleep", action="store_true", help="let Windows sleep")
    parser.add_argument(
        "--network-waits", default=NETWORK_WAITS_MIN,
        help="minutes to wait before each retry after the network went down",
    )
    parser.add_argument(
        "--daily-pages", type=int, default=0,
        help="stop each tier after N live pages in a local day, wait for the next day and "
             "continue (0 = off; waits stay inside keep-awake unless --allow-sleep)",
    )
    parser.add_argument(
        "--window", default=None,
        help="crawl only between HH:MM-HH:MM local time, waiting outside it; overnight "
             "windows wrap, e.g. 22:00-06:00 (waits stay inside keep-awake unless --allow-sleep)",
    )
    parser.add_argument(
        "--day-start", default="00:00",
        help="local HH:MM at which the daily page budget resets (default 00:00)",
    )
    parser.add_argument("--stall-minutes", type=float, default=STALL_SECS / 60,
                        help=argparse.SUPPRESS)
    parser.add_argument("--watch-seconds", type=float, default=WATCH_SECS, help=argparse.SUPPRESS)
    parser.add_argument("--pause-seconds", type=float, default=PAUSE_SECS, help=argparse.SUPPRESS)
    parser.add_argument(
        "-s", dest="settings", action="append", default=[], type=parse_override,
        metavar="KEY=VALUE", help="override a Scrapy setting for every tier",
    )
    args = parser.parse_args(argv)
    tiers = [tier.strip() for tier in args.tiers.split(",") if tier.strip()]
    unknown = sorted(set(tiers) - set(TIERS) - set(EXTRA_TIERS))
    if unknown:
        parser.error(
            f"unknown tier(s) {', '.join(unknown)}; "
            f"choose from {', '.join(TIERS + EXTRA_TIERS)}"
        )
    network_waits = [float(m) for m in args.network_waits.split(",") if m.strip()]
    window = None
    try:
        parse_hhmm(args.day_start)
        if args.window:
            window = parse_window(args.window)
    except ValueError as exc:
        parser.error(str(exc))

    if not contact():
        print(f"error: {MISSING_CONTACT_HELP}", file=sys.stderr)
        return 2
    overrides = dict(args.settings)
    refused = refused_overrides(overrides, THREEDECKS_BASE_URL)
    if refused:
        print(refusal_message(refused, THREEDECKS_BASE_URL), file=sys.stderr)
        return 2

    sys.stdout.reconfigure(errors="replace")  # ship names may not fit the console code page
    data_dir = Path(DATA_DIR)
    log = Log(data_dir / "logs" / f"crawl-{time.strftime('%Y%m%d-%H%M%S')}.log")
    try:
        # One crawl per data dir: a second would fetch the same pending ids and
        # double the rate (see threedecks.lock). The lock covers the whole chain.
        with CrawlLock(data_dir / "crawl.lock"):
            return crawl(args, tiers, network_waits, overrides, data_dir, log, window)
    except CrawlLockHeld as held:
        log.say(f"another crawl holds {data_dir} (pid {held.pid}, started {held.started}); "
                "its log and heartbeat live there")
        return 2
    finally:
        log.close()


def crawl(args, tiers, network_waits, overrides, data_dir: Path, log: Log, window=None) -> int:
    log.say(f"log file: {log.path}")
    with StateStore(data_dir / "state.sqlite") as store:
        closed = store.close_open_runs()
    if closed:
        log.say(f"marked {closed} run(s) that never finished as 'interrupted'")
    if pending_reboot():
        log.say("warning: Windows has an update waiting to restart this PC, which would stop "
                "the crawl. Restart first, or pause updates (Settings > Windows Update).")

    started, start_count = time.time(), ship_count(data_dir)
    if args.more is not None:
        args.ships = start_count + args.more
    log.say(f"{start_count} ship records stored; target {args.ships}")
    status, verdict = 0, f"every tier finished below the target of {args.ships}"
    with keep_awake(not args.allow_sleep) as awake:
        if awake:
            log.say("keeping the PC awake until the crawl ends (the screen stays on)")
        for spider in tiers:
            is_ship_tier = spider in TIERS
            if is_ship_tier and ship_count(data_dir) >= args.ships:
                verdict = f"target of {args.ships} reached"
                break
            finished_at = tier_finished(data_dir, spider)
            if finished_at and not args.rerun:
                log.say(f"skipping {spider}: it finished at {finished_at} (--rerun replays it)")
                continue
            restarts = network_retries = 0
            while True:
                remaining = 0
                if args.daily_pages:
                    remaining = args.daily_pages - pages_today(data_dir, args.day_start)
                    if remaining <= 0:
                        minutes = (next_day_start(time.time(), args.day_start)
                                   - time.time()) / 60
                        log.say(f"daily budget of {args.daily_pages} reached; waiting until "
                                f"{args.day_start} ({minutes:.0f} min)")
                        if not wait_minutes(minutes, log):
                            result = TierResult(code=None, interrupted=True)
                            break
                        continue
                if window is not None:
                    seconds = window_wait_seconds(time.time(), window)
                    if seconds > 0:
                        log.say(f"outside the crawl window; waiting {seconds / 60:.0f} min "
                                "until it opens")
                        if not wait_minutes(seconds / 60, log):
                            result = TierResult(code=None, interrupted=True)
                            break
                        continue
                # At least the download delay since the last request of any earlier
                # process: a new crawl sends robots.txt the moment it opens.
                if not wait_minutes(args.pause_seconds / 60, log):
                    result = TierResult(code=None, interrupted=True)
                    break
                log.say(f"=== {spider} ===")
                result = run_tier(spider, args.ships if is_ship_tier else None,
                                  overrides, data_dir, log,
                                  stall_secs=args.stall_minutes * 60,
                                  watch_secs=args.watch_seconds,
                                  daily_pages=remaining,
                                  stop_at=window_end_epoch(time.time(), window) if window else 0.0)
                run = last_run(data_dir, spider) or {}
                reason = run.get("close_reason")
                if result.stalled and restarts < MAX_RESTARTS:
                    restarts += 1
                    log.say(f"restarting {spider} ({restarts} of {MAX_RESTARTS})")
                    continue
                if reason == "network_down" and network_retries < len(network_waits):
                    minutes = network_waits[network_retries]
                    network_retries += 1
                    log.say(f"the network or the site is not answering; retrying {spider} "
                            f"in {minutes:g} min ({network_retries} of {len(network_waits)})")
                    if wait_minutes(minutes, log):
                        continue
                    result.interrupted = True
                if reason == "daily_budget":
                    minutes = (next_day_start(time.time(), args.day_start) - time.time()) / 60
                    log.say(f"daily budget reached; waiting until {args.day_start} "
                            f"({minutes:.0f} min), then rerunning {spider}")
                    if wait_minutes(minutes, log):
                        continue
                    result.interrupted = True
                if reason == "window_closed" and window is not None:
                    minutes = window_wait_seconds(time.time(), window) / 60
                    log.say(f"the crawl window closed; waiting {minutes:.0f} min for the next "
                            f"one, then rerunning {spider}")
                    if wait_minutes(minutes, log):
                        continue
                    result.interrupted = True
                break
            if result.interrupted:
                status, verdict = 130, f"stopped by Ctrl+C during {spider}; rerun to resume"
                break
            if result.stalled:
                status, verdict = 1, f"{spider} kept stalling; see the log, then rerun"
                break
            if result.code != 0:
                status, verdict = 1, f"{spider} exited with code {result.code}; see the log"
                break
            if reason == SHIP_TARGET_REASON:
                verdict = f"target of {args.ships} reached during {spider}"
                break
            if reason == "blocked":
                status, verdict = 1, (
                    f"{spider} closed 'blocked' after its cool-offs. Rule 5: the next tier was "
                    "not started. Investigate and contact the site owner before resuming."
                )
                break
            if reason == "incomplete_streak":
                status, verdict = 1, (
                    f"{spider} closed 'incomplete_streak': {THREEDECKS_INCOMPLETE_LIMIT} ship "
                    "pages in a row failed the completeness check; the site may be serving "
                    "truncated pages or the markup changed. Run scripts/smoke.py, investigate, "
                    "then rerun."
                )
                break
            if reason == "network_down":
                status, verdict = 1, "the network stayed down through every retry; rerun later"
                break
            if reason == "closespider_pagecount":  # a smoke run's page cap, not a failure
                verdict = f"page cap reached during {spider}"
                break
            if reason == TARGETED_CLOSE_REASON:  # a targeted run, not the full tier
                verdict = f"targeted run finished during {spider}"
                break
            if reason != "finished":
                status, verdict = 1, f"{spider} closed with reason {reason!r}; stopping"
                break

    end_count = ship_count(data_dir)
    hours = (time.time() - started) / 3600
    log.say(
        f"{verdict}. {end_count} ship records stored "
        f"({end_count - start_count:+d} in {hours:.1f} h). "
        "Progress: uv run python scripts/crawl_status.py"
    )
    if status not in (0, 130):  # failed; status 130 is Ctrl+C, with a person present
        notify("Three Decks crawl stopped", verdict, log)
    return status


if __name__ == "__main__":
    raise SystemExit(main())
