"""A dependency-free polling watcher.

Every ``poll_interval`` seconds it scans the top level of the watched folders
and sorts any file that is *finished* — i.e. its size has been stable across a
scan and it is older than ``settle_seconds``. Polling (vs. inotify/watchdog)
keeps the tool pure-stdlib and sidesteps mid-download events entirely.

Home-folder safety: at startup the watcher snapshots everything already at the
top level of ``~`` and ignores all of it forever. Only files that appear after
start are eligible, so files you deliberately keep in home are never swept.
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path

from .config import Config, LOCK_FILE
from .core import MoveResult, is_eligible, sort_file
from .notify import notify_results


class SingleInstanceError(RuntimeError):
    pass


class _Lock:
    """A PID lockfile so the daemon and a manual watcher cannot both run."""

    def __init__(self, path: Path = LOCK_FILE):
        self.path = path

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            try:
                pid = int(self.path.read_text().strip())
            except (ValueError, OSError):
                pid = None
            if pid and _pid_alive(pid):
                raise SingleInstanceError(
                    f"Already running (pid {pid}). Lock: {self.path}")
        self.path.write_text(str(os.getpid()))

    def release(self) -> None:
        try:
            self.path.unlink()
        except OSError:
            pass


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


class Watcher:
    def __init__(self, cfg: Config, *, on_event=None):
        self.cfg = cfg
        self.on_event = on_event or (lambda msg: None)
        self._pending: dict[str, int] = {}   # path → last seen size
        self._home_ignore: set[str] = set()
        self._running = False

    # ── lifecycle ──────────────────────────────────────────────────────────────

    def run(self) -> None:
        lock = _Lock()
        lock.acquire()
        self._running = True
        try:
            self._seed_home_ignore()
            self._log(f"watching downloads: {self.cfg.downloads_dir}")
            if self.cfg.watch_home:
                self._log(f"watching home (new files only): {self.cfg.home_dir}")
            if self.cfg.sort_delay_seconds > self.cfg.settle_seconds:
                self._log(f"grace period: {self.cfg.sort_delay_seconds:.0f}s "
                          "before a file is autosorted")
            if self.cfg.dry_run:
                self._log("DRY-RUN — nothing will actually move")
            if self.cfg.sort_existing_on_start:
                self._sort_existing_downloads()
            while self._running:
                self._tick()
                time.sleep(self.cfg.poll_interval)
        finally:
            lock.release()

    def stop(self) -> None:
        self._running = False

    # ── startup helpers ────────────────────────────────────────────────────────

    def _seed_home_ignore(self) -> None:
        if not self.cfg.watch_home:
            return
        for entry in _top_level(Path(self.cfg.home_dir)):
            self._home_ignore.add(str(entry))

    def _sort_existing_downloads(self) -> None:
        # Sort files already loose in Downloads at startup, but honour the grace
        # period: anything younger than the threshold is left for the scan loop to
        # pick up once it has aged enough.
        results = []
        now = time.time()
        threshold = max(self.cfg.settle_seconds, self.cfg.sort_delay_seconds)
        for entry in _top_level(Path(self.cfg.downloads_dir)):
            if not is_eligible(entry, self.cfg, home=False):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            if (now - st.st_mtime) >= threshold:
                results.append(sort_file(entry, self.cfg))
        self._report(results)

    # ── per-scan work ──────────────────────────────────────────────────────────

    def _tick(self) -> None:
        results = self._scan(Path(self.cfg.downloads_dir), home=False)
        if self.cfg.watch_home:
            results += self._scan(Path(self.cfg.home_dir), home=True)
        self._report(results)

    def _scan(self, folder: Path, *, home: bool) -> list[MoveResult]:
        results: list[MoveResult] = []
        seen_now: set[str] = set()
        for entry in _top_level(folder):
            key = str(entry)
            seen_now.add(key)
            if home and key in self._home_ignore:
                continue
            if not is_eligible(entry, self.cfg, home=home):
                continue
            try:
                st = entry.stat()
            except OSError:
                continue
            stable_size = self._pending.get(key) == st.st_size
            # A file must be size-stable AND past the grace period before it is
            # moved. settle_seconds detects a finished download; sort_delay_seconds
            # is the deliberate wait that keeps a fresh file in Downloads.
            threshold = max(self.cfg.settle_seconds, self.cfg.sort_delay_seconds)
            old_enough = (time.time() - st.st_mtime) >= threshold
            if stable_size and old_enough:
                self._pending.pop(key, None)
                results.append(sort_file(entry, self.cfg))
            else:
                self._pending[key] = st.st_size
        # Forget files that are gone (moved or deleted). Match on the immediate
        # parent, NOT a path prefix: when Downloads lives *inside* home, a prefix
        # match would let the home scan wipe Downloads' pending state every tick,
        # so files there would never register as size-stable.
        for key in list(self._pending):
            if Path(key).parent == folder and key not in seen_now:
                self._pending.pop(key, None)
        return results

    # ── reporting ──────────────────────────────────────────────────────────────

    def _report(self, results: list[MoveResult]) -> None:
        for r in results:
            if r.action in ("moved", "dry-run", "duplicate"):
                verb = "would move" if r.action == "dry-run" else r.action
                self._log(f"{verb}: {r.src.name} → {r.category}"
                          + (f" ({r.detail})" if r.detail else ""))
            elif r.action == "error":
                self._log(f"error: {r.src.name}: {r.detail}")
        notify_results(results, self.cfg.notifications)

    def _log(self, msg: str) -> None:
        print(msg, flush=True)
        self.on_event(msg)


def _top_level(folder: Path):
    """Yield immediate children of *folder* (non-recursive). Never raises."""
    try:
        yield from folder.iterdir()
    except OSError:
        return
