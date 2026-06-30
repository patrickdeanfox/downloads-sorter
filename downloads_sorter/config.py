"""Configuration: defaults, the extension→folder map, and TOML load/save.

The config lives at ``~/.config/downloads-sorter/config.toml`` and is plain
TOML so you can hand-edit it. Reading uses the stdlib ``tomllib``; writing uses
a tiny serializer below (good enough for this constrained schema, and covered
by a round-trip test).
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, asdict
from pathlib import Path


# ── XDG locations ──────────────────────────────────────────────────────────────

def _xdg(env: str, default: Path) -> Path:
    val = os.environ.get(env)
    return Path(val) if val else default


CONFIG_DIR = _xdg("XDG_CONFIG_HOME", Path.home() / ".config") / "downloads-sorter"
STATE_DIR = _xdg("XDG_STATE_HOME", Path.home() / ".local" / "state") / "downloads-sorter"

CONFIG_PATH = CONFIG_DIR / "config.toml"
MOVES_LOG = STATE_DIR / "moves.log"
LOCK_FILE = STATE_DIR / "watcher.lock"


# ── Default extension → category map ───────────────────────────────────────────
# Order matters only for documentation; lookups are by extension.

DEFAULT_FOLDERS: dict[str, list[str]] = {
    "Documents": [".pdf", ".doc", ".docx", ".odt", ".rtf", ".txt", ".md",
                  ".tex", ".csv", ".xls", ".xlsx", ".ods", ".ppt", ".pptx",
                  ".odp", ".pages", ".numbers", ".key"],
    "Images": [".jpg", ".jpeg", ".png", ".gif", ".bmp", ".svg", ".webp",
               ".heic", ".heif", ".tiff", ".tif", ".raw", ".ico", ".avif"],
    "Archives": [".zip", ".tar", ".gz", ".tgz", ".rar", ".7z", ".bz2", ".xz",
                 ".zst", ".tar.gz", ".tar.bz2", ".tar.xz"],
    "Installers": [".exe", ".deb", ".rpm", ".appimage", ".msi", ".dmg", ".run",
                   ".flatpakref", ".snap", ".apk", ".pkg"],
    "DiskImages": [".iso", ".img"],
    "Web": [".html", ".htm", ".mhtml", ".webloc", ".url", ".maff"],
    "Media": [".mp4", ".mkv", ".mp3", ".flac", ".wav", ".avi", ".mov", ".m4a",
              ".ogg", ".webm", ".m4v", ".opus", ".aac", ".wma", ".flv"],
    "Code": [".py", ".js", ".ts", ".jsx", ".tsx", ".json", ".yaml", ".yml",
             ".sh", ".bash", ".zsh", ".rs", ".go", ".c", ".cpp", ".h", ".java",
             ".rb", ".php", ".cs", ".swift", ".kt", ".lua", ".r", ".sql",
             ".toml", ".ini", ".cfg", ".conf", ".ipynb"],
    "Ebooks": [".epub", ".mobi", ".azw3", ".djvu", ".fb2"],
    "Fonts": [".ttf", ".otf", ".woff", ".woff2"],
    "Torrents": [".torrent"],
    "Misc": [],
}

# Filenames ending in these are still being written — never touch them.
DEFAULT_SKIP_SUFFIXES = [".part", ".crdownload", ".download", ".opdownload",
                         ".tmp", ".partial", ".!ut"]

# Category folder used for files that already exist (identical) at the target.
DUPLICATES_FOLDER = "Duplicates"


@dataclass
class Config:
    """All tunable settings. Paths are absolute strings on disk."""

    downloads_dir: str = str(Path.home() / "Downloads")
    home_dir: str = str(Path.home())
    watch_home: bool = True
    # When set (e.g. "Sorted"), categories nest under downloads_dir/<this>/.
    # Empty string means categories live directly in downloads_dir.
    sorted_subfolder: str = ""
    dry_run: bool = False
    notifications: bool = True
    poll_interval: float = 2.0          # seconds between scans
    settle_seconds: float = 2.0         # min age before a file is "finished"
    sort_existing_on_start: bool = True  # sort loose files already in Downloads
    on_duplicate: str = "move"          # "move" → Duplicates folder | "skip" | "delete"
    skip_suffixes: list[str] = field(default_factory=lambda: list(DEFAULT_SKIP_SUFFIXES))
    # Exact filenames to never move (e.g. working/project files kept in home).
    ignore_names: list[str] = field(default_factory=list)
    folders: dict[str, list[str]] = field(
        default_factory=lambda: {k: list(v) for k, v in DEFAULT_FOLDERS.items()})

    # ── derived helpers ───────────────────────────────────────────────────────

    @property
    def output_base(self) -> Path:
        base = Path(self.downloads_dir)
        return base / self.sorted_subfolder if self.sorted_subfolder else base

    def ext_map(self) -> dict[str, str]:
        """Build {'.pdf': 'Documents', ...} from the folders map."""
        m: dict[str, str] = {}
        for folder, exts in self.folders.items():
            for ext in exts:
                m[ext.lower()] = folder
        return m


# ── TOML I/O ───────────────────────────────────────────────────────────────────

def load_config(path: Path = CONFIG_PATH) -> Config:
    """Load config from TOML, falling back to defaults for missing keys."""
    cfg = Config()
    if not path.exists():
        return cfg
    with open(path, "rb") as f:
        data = tomllib.load(f)
    folders = data.pop("folders", None)
    for key, value in data.items():
        if hasattr(cfg, key):
            setattr(cfg, key, value)
    if isinstance(folders, dict):
        cfg.folders = {k: list(v) for k, v in folders.items()}
    return cfg


def _toml_escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return repr(v)
    if isinstance(v, str):
        return f'"{_toml_escape(v)}"'
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    raise TypeError(f"Cannot serialize {type(v)!r} to TOML")


def dumps_config(cfg: Config) -> str:
    """Serialize a Config to TOML text (round-trips through tomllib)."""
    d = asdict(cfg)
    folders = d.pop("folders")
    lines = ["# downloads-sorter configuration",
             "# Edit and the running service will pick it up on its next restart.",
             ""]
    for key, value in d.items():
        lines.append(f"{key} = {_toml_value(value)}")
    lines.append("")
    lines.append("[folders]")
    lines.append("# category = [list of extensions]. Files matching nothing go to Misc.")
    for name, exts in folders.items():
        lines.append(f"{name} = {_toml_value(exts)}")
    lines.append("")
    return "\n".join(lines)


def save_config(cfg: Config, path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dumps_config(cfg))
