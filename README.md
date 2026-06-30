# downloads-sorter

Watch your **Downloads** folder (and, safely, the top level of your **home**
folder) and file every finished download into a folder chosen by its type —
`Documents/`, `Images/`, `Media/`, `Code/`, and so on.

No AI. No network. No third-party packages. Just the Python standard library
(3.11+) running quietly as a background service.

```
~/Downloads/
├── invoice.pdf        ─┐
├── holiday.png         │  before
├── album.mp3          ─┘
   ↓ downloads-sorter ↓
~/Downloads/
├── Documents/invoice.pdf
├── Images/holiday.png
└── Media/album.mp3
```

## Why it exists

Browsers dump everything into one folder (and occasionally into your home
folder). This tool keeps that tidy automatically: the moment a download
finishes, it lands in the right category folder. Every move is logged and
reversible.

## How it works

- A **polling watcher** scans the top level of the watched folders every couple
  of seconds. It only acts on files that are *finished* — stable in size and a
  little older than `settle_seconds` — so half-downloaded files (`.crdownload`,
  `.part`, …) are never touched.
- Files keep their **original names**; they are only moved, never renamed.
- **Duplicate handling:** if an identical file (same size + SHA-256) already
  exists in the target, the new copy is moved into a `Duplicates/` folder
  instead of overwriting. Name clashes with *different* content get a `-1`,
  `-2`, … suffix.
- Every move is recorded in a CSV log so it can be undone.

### Home-folder safety

Watching your whole home folder would be dangerous — it's full of files you
keep there on purpose. So the rule is deliberately conservative:

1. Only the **top level** of `~` is considered (never subfolders, never dotfiles).
2. Only **known file types** are moved (anything that would land in `Misc` is
   left alone).
3. **Pre-existing files are never swept.** At startup the watcher snapshots
   everything already in `~` and ignores all of it — only files that appear
   *after* the service starts are eligible.

Downloads, by contrast, gets its existing loose files sorted on start (toggle
with `sort_existing_on_start`). You can disable home watching entirely with
`watch_home = false`.

## Install

```bash
git clone https://github.com/patrickdeanfox/downloads-sorter.git
cd downloads-sorter
./packaging/install.sh
```

The installer:
- verifies the package imports,
- writes a default config to `~/.config/downloads-sorter/config.toml` (if absent),
- installs and **enables** a `systemd --user` service (starts on login),
- installs a desktop launcher for the GUI.

Check it:

```bash
systemctl --user status downloads-sorter.service
journalctl --user -u downloads-sorter.service -f
```

Uninstall (keeps your config, history, and sorted files):

```bash
./packaging/uninstall.sh
```

## Usage

The service runs on its own. For everything else:

```bash
# Sort whatever is already loose in Downloads, then exit
python3 -m downloads_sorter --once

# Preview without moving anything
python3 -m downloads_sorter --once --dry-run

# Undo the last N moves
python3 -m downloads_sorter --undo 3

# Show effective settings
python3 -m downloads_sorter --print-config

# Run the watcher in the foreground (Ctrl+C to stop)
python3 -m downloads_sorter --watch
```

### GUI control panel

```bash
python3 -m downloads_sorter.gui
```

A small dark-themed window to start/stop the service, enable it on login, run a
one-shot sort, browse the move history (with **undo selected**), see stats, and
edit settings.

## Configuration

`~/.config/downloads-sorter/config.toml` — plain TOML, hand-editable. The
service picks up changes on its next restart (`systemctl --user restart
downloads-sorter`), or save from the GUI which restarts it for you.

| Key | Default | Meaning |
|-----|---------|---------|
| `downloads_dir` | `~/Downloads` | Folder to watch and sort into |
| `home_dir` | `~` | Home folder to watch (top level only) |
| `watch_home` | `true` | Watch home for *new* downloads |
| `sorted_subfolder` | `""` | If set (e.g. `"Sorted"`), nest categories under it |
| `dry_run` | `false` | Preview only — never move |
| `notifications` | `true` | Desktop notifications via `notify-send` |
| `poll_interval` | `2.0` | Seconds between scans |
| `settle_seconds` | `2.0` | Min file age before it's "finished" |
| `sort_existing_on_start` | `true` | Sort loose Downloads files at startup |
| `on_duplicate` | `"move"` | `move` → Duplicates / `skip` / `delete` |
| `skip_suffixes` | `.part`, `.crdownload`, … | In-progress files to ignore |
| `[folders]` | see file | `category = [extensions]` map |

Edit the `[folders]` table to add extensions or new categories.

## Browser integration

The watcher is **browser-agnostic** — it reacts to files appearing on disk, so
it works with Chrome, Firefox, and any other download manager with zero setup.
It detects completion by the file becoming stable, which is more reliable than
hooking a fixed timer.

If you ever want *source-aware* rules ("anything from github.com → Code"), that
requires a browser extension plus a native-messaging host to pass the source URL
to the sorter. That's intentionally **not** built here to keep things simple;
the code is structured so it could be added later without a rewrite. See
[ROADMAP](#roadmap).

## Development

```bash
pip install -e ".[dev]"
pytest
```

The sorting logic in `core.py` is pure and fully unit-tested (no filesystem
state beyond `tmp_path`, no services).

## Roadmap

- Optional browser extension + native-messaging host for URL/source-based rules.
- Per-rule matching by filename pattern and size, not just extension.
- Optional date sub-buckets (`Documents/2026-06/…`).

## License

MIT — see [LICENSE](LICENSE).
