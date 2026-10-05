"""Single-instance lock for scripts/crawl.py and scripts/smoke.py.

Two crawls over the same ``data/threedecks`` would fetch the same pending ids,
doubling the request rate against the owner's 5 s condition. The lock is held by
the OS (``msvcrt.locking`` on Windows, ``fcntl.flock`` elsewhere), which releases
it when the process dies — crash, kill or power cut — so no stale-lock logic is
needed.

The lock covers one byte of the lock file; the holder writes its pid and start
time before that byte, where a contender can read them (the locked byte itself
is not readable by other processes on Windows).
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

_LOCK_OFFSET = 64  # the byte the OS lock covers
_INFO_BYTES = _LOCK_OFFSET  # the holder's pid and start time live before it


class CrawlLockHeld(RuntimeError):
    """Another process holds the crawl lock."""

    def __init__(self, pid: str, started: str) -> None:
        self.pid = pid
        self.started = started
        super().__init__(f"another crawl holds the lock (pid {pid}, started {started})")


def holder(path: Path | str) -> tuple[str, str]:
    """The current holder's ``(pid, start time)`` as written to the lock file.

    Reads exactly the info bytes with an unbuffered read: a buffered reader can
    fetch a whole block and trip over the OS-locked byte past this region.
    """
    try:
        fd = os.open(str(path), os.O_RDONLY)
        try:
            data = os.read(fd, _INFO_BYTES)
        finally:
            os.close(fd)
    except OSError:
        return "?", "?"
    text = data.decode("utf-8", "replace").rstrip("\0 ").strip()
    pid, _, started = text.partition(" ")
    return pid or "?", started or "?"


class CrawlLock:
    """Context manager holding an OS lock on ``path`` for the whole block."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._fd: int | None = None

    def __enter__(self) -> CrawlLock:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(str(self.path), os.O_RDWR | os.O_CREAT, 0o666)
        try:
            self._acquire(fd)
        except OSError:
            os.close(fd)
            raise CrawlLockHeld(*holder(self.path)) from None
        self._fd = fd
        # Write only once the lock is held: written earlier, a contender would
        # clobber the current holder's info before finding out the lock is taken.
        try:
            info = f"{os.getpid()} {time.strftime('%Y-%m-%dT%H:%M:%S')}".encode()
            os.lseek(fd, 0, os.SEEK_SET)
            os.write(fd, info.ljust(_INFO_BYTES))
        except OSError:  # best-effort; the lock itself is what gates the crawl
            pass
        return self

    def __exit__(self, *exc) -> None:
        fd, self._fd = self._fd, None
        if fd is None:
            return
        try:
            self._release(fd)
        finally:
            os.close(fd)

    def _acquire(self, fd: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

    def _release(self, fd: int) -> None:
        if sys.platform == "win32":
            import msvcrt

            os.lseek(fd, _LOCK_OFFSET, os.SEEK_SET)
            msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(fd, fcntl.LOCK_UN)
