"""Core sorting logic: categorize a file, choose a safe destination, move it.

Everything here is deliberately side-effect-light and unit-testable. The only
functions that touch the filesystem are :func:`sort_file` and :func:`undo`.
"""

from __future__ import annotations

import csv
import hashlib
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from .config import Config, MOVES_LOG, DUPLICATES_FOLDER

# Compound extensions must be checked before the single-suffix fallback,
# otherwise "archive.tar.gz" would categorize as ".gz" and lose ".tar".
_COMPOUND = (".tar.gz", ".tar.bz2", ".tar.xz")


# ── name / extension helpers ───────────────────────────────────────────────────

def split_name(filename: str) -> tuple[str, str]:
    """Split into (stem, suffix), honouring compound suffixes like .tar.gz."""
    lower = filename.lower()
    for comp in _COMPOUND:
        if lower.endswith(comp) and len(filename) > len(comp):
            return filename[: -len(comp)], filename[-len(comp):]
    p = Path(filename)
    return p.stem, p.suffix


def extension_of(filename: str) -> str:
    return split_name(filename)[1].lower()


def categorize(filename: str, ext_map: dict[str, str]) -> str:
    """Return the destination category for *filename* (``"Misc"`` if unknown)."""
    return ext_map.get(extension_of(filename), "Misc")


# ── eligibility ────────────────────────────────────────────────────────────────

def is_partial(filename: str, skip_suffixes: list[str]) -> bool:
    """True for in-progress / temp files that should never be moved."""
    lower = filename.lower()
    if lower.endswith("~"):
        return True
    return any(lower.endswith(s) for s in skip_suffixes)


def is_eligible(path: Path, cfg: Config, *, home: bool) -> bool:
    """Whether a top-level entry should be considered for sorting.

    ``home=True`` applies the stricter home-folder rule: only known file types
    are touched (anything that would land in Misc is left alone).
    """
    name = path.name
    if name.startswith("."):
        return False
    if is_partial(name, cfg.skip_suffixes):
        return False
    try:
        if not path.is_file():
            return False
    except OSError:
        return False
    if home and categorize(name, cfg.ext_map()) == "Misc":
        return False
    return True


# ── duplicate detection ────────────────────────────────────────────────────────

def _sha256(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(chunk), b""):
            h.update(block)
    return h.hexdigest()


def files_identical(a: Path, b: Path) -> bool:
    """Cheap size check first, full hash only if sizes match."""
    try:
        if a.stat().st_size != b.stat().st_size:
            return False
        return _sha256(a) == _sha256(b)
    except OSError:
        return False


def uniquify(dest: Path) -> Path:
    """Return *dest* or the first ``name-N`` variant that does not exist."""
    if not dest.exists():
        return dest
    stem, suffix = split_name(dest.name)
    i = 1
    while True:
        candidate = dest.with_name(f"{stem}-{i}{suffix}")
        if not candidate.exists():
            return candidate
        i += 1


# ── planning + moving ──────────────────────────────────────────────────────────

@dataclass
class MoveResult:
    action: str          # "moved" | "duplicate" | "skipped" | "dry-run" | "error"
    src: Path
    dest: Path | None
    category: str
    detail: str = ""


def destination_for(path: Path, cfg: Config) -> tuple[str, Path]:
    """Return (category, destination_path) keeping the original filename."""
    category = categorize(path.name, cfg.ext_map())
    return category, cfg.output_base / category / path.name


def _log_move(src: Path, dest: Path, dry_run: bool) -> None:
    MOVES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(MOVES_LOG, "a", newline="") as f:
        csv.writer(f).writerow([
            datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "DRY-RUN" if dry_run else "MOVED",
            str(src), str(dest),
        ])


def sort_file(path: Path, cfg: Config, *, log: bool = True) -> MoveResult:
    """Move a single file into its category folder. The heart of the tool."""
    category, dest = destination_for(path, cfg)

    # Already-sorted file with identical content → handle as duplicate.
    if dest.exists() and dest != path and files_identical(path, dest):
        return _handle_duplicate(path, cfg, category, log=log)

    if dest.exists() and dest != path:
        dest = uniquify(dest)

    if cfg.dry_run:
        if log:
            _log_move(path, dest, dry_run=True)
        return MoveResult("dry-run", path, dest, category, "would move")

    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
    except FileNotFoundError:
        return MoveResult("skipped", path, None, category, "vanished before move")
    except OSError as e:
        return MoveResult("error", path, dest, category, str(e))

    if log:
        _log_move(path, dest, dry_run=False)
    return MoveResult("moved", path, dest, category)


def _handle_duplicate(path: Path, cfg: Config, category: str, *,
                      log: bool) -> MoveResult:
    if cfg.on_duplicate == "skip":
        return MoveResult("duplicate", path, None, category, "identical copy exists")
    if cfg.on_duplicate == "delete":
        if not cfg.dry_run:
            try:
                path.unlink()
            except OSError as e:
                return MoveResult("error", path, None, category, str(e))
        return MoveResult("duplicate", path, None, category, "deleted (identical copy exists)")
    # default: move into a Duplicates folder so it leaves the top level
    dest = uniquify(cfg.output_base / DUPLICATES_FOLDER / path.name)
    if cfg.dry_run:
        return MoveResult("dry-run", path, dest, DUPLICATES_FOLDER, "would move (duplicate)")
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), str(dest))
    except OSError as e:
        return MoveResult("error", path, dest, DUPLICATES_FOLDER, str(e))
    if log:
        _log_move(path, dest, dry_run=False)
    return MoveResult("duplicate", path, dest, DUPLICATES_FOLDER, "moved to Duplicates")


# ── undo ───────────────────────────────────────────────────────────────────────

def read_moves() -> list[list[str]]:
    if not MOVES_LOG.exists():
        return []
    with open(MOVES_LOG, newline="") as f:
        return [row for row in csv.reader(f) if len(row) == 4]


def _rewrite_moves(rows: list[list[str]]) -> None:
    MOVES_LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(MOVES_LOG, "w", newline="") as f:
        csv.writer(f).writerows(rows)


def undo_rows(targets: list[list[str]]) -> list[str]:
    """Reverse the specific MOVED *targets*. Returns human-readable result lines."""
    rows = read_moves()
    out: list[str] = []
    undone: list[list[str]] = []
    for row in targets:
        if row[1] != "MOVED":
            continue
        _, _, src, dst = row
        src_path, dst_path = Path(src), Path(dst)
        if not dst_path.exists():
            out.append(f"[skip] missing: {dst_path.name}")
            continue
        try:
            src_path.parent.mkdir(parents=True, exist_ok=True)
            dst_path.rename(src_path)
            out.append(f"restored: {dst_path.name} → {src_path}")
            undone.append(row)
        except OSError as e:
            out.append(f"[error] {dst_path.name}: {e}")

    if undone:
        _rewrite_moves([r for r in rows if r not in undone])
    out.append(f"Undid {len(undone)} move(s).")
    return out


def undo(n: int = 1) -> list[str]:
    """Reverse the last *n* real moves (newest first)."""
    moved = [r for r in read_moves() if r[1] == "MOVED"]
    if not moved:
        return ["Nothing to undo."]
    return undo_rows(list(reversed(moved[-n:])))
