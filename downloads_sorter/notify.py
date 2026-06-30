"""Best-effort desktop notifications via ``notify-send``.

Never raises: if notifications are off or ``notify-send`` is unavailable, the
calls are silently no-ops so the watcher keeps running headless.
"""

from __future__ import annotations

import shutil
import subprocess

_HAVE_NOTIFY_SEND = shutil.which("notify-send") is not None
_APP = "Downloads Sorter"


def notify(summary: str, body: str = "") -> None:
    if not _HAVE_NOTIFY_SEND:
        return
    try:
        subprocess.run(
            ["notify-send", "--app-name", _APP, "--icon", "folder-download",
             summary, body],
            check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except OSError:
        pass


def notify_results(results, enabled: bool) -> None:
    """Summarize a tick's moves into one notification (or a per-file one)."""
    if not enabled:
        return
    moved = [r for r in results if r.action in ("moved", "duplicate") and r.dest]
    if not moved:
        return
    if len(moved) == 1:
        r = moved[0]
        notify(f"Sorted → {r.category}", r.src.name)
    else:
        notify(f"Sorted {len(moved)} files", "Filed into category folders")
