# Changelog

All notable changes to this project are documented here.
The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added
- `--once --include-home`: a deliberate one-time sweep of the existing backlog
  of loose downloads in the top level of the home folder (known types only).
- `ignore_names` config option: exact filenames that are never moved, so
  working/project files kept in home (e.g. `package-lock.json`) are protected
  from sweeps everywhere.

### Fixed
- `--dry-run` is no longer baked into the auto-created config file; a transient
  preview run could leave `dry_run=true` on disk and silence later real runs.

## [1.0.0] — 2026-06-30

First release. A ground-up simplification of an earlier "AI Downloads Sorter".

### Added
- Dependency-free polling watcher for `~/Downloads` and (safely) the top level
  of `~`, written against the Python 3.11+ standard library only.
- Sorting into category folders by file type, keeping original filenames.
- Conservative home-folder rules: top level only, known types only, and
  pre-existing files are never swept.
- Completed-download detection (size-stable + `settle_seconds`) so in-progress
  files (`.crdownload`, `.part`, …) are ignored.
- Duplicate handling (identical → `Duplicates/`) and collision-safe renaming.
- Reversible moves via a CSV log; `--undo N` and "undo selected" in the GUI.
- `systemd --user` service with install/uninstall scripts and a desktop launcher.
- Slimmed Tkinter control panel: service control, one-shot sort, history, stats,
  settings editor.
- TOML config at `~/.config/downloads-sorter/config.toml`.
- Desktop notifications via `notify-send` (best-effort, optional).
- Unit tests for the core logic and config round-trip.

### Removed (from the predecessor)
- The entire AI/LLM layer: Ollama integration, content-aware renaming, PDF text
  extraction, and code version detection.
- The `watchdog`, `requests`, and `pdfminer` dependencies.
