"""Command-line interface.

    downloads-sorter --watch          # run the watcher (used by the service)
    downloads-sorter --once           # sort what's already loose in Downloads
    downloads-sorter --undo [N]       # reverse the last N moves
    downloads-sorter --print-config   # show effective settings

Global flags: --dry-run, --config PATH.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import CONFIG_PATH, load_config, save_config
from .core import is_eligible, sort_file, undo
from .watcher import Watcher, SingleInstanceError, _top_level


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="downloads-sorter",
        description="Watch folders and file new downloads into category folders.")
    p.add_argument("--version", action="version",
                   version=f"downloads-sorter {__version__}")
    p.add_argument("--config", type=Path, default=CONFIG_PATH,
                   help=f"config file (default: {CONFIG_PATH})")
    p.add_argument("--dry-run", action="store_true",
                   help="preview moves without touching any files")

    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true",
                      help="run continuously (the long-lived service mode)")
    mode.add_argument("--once", action="store_true",
                      help="sort files already loose in Downloads, then exit")
    mode.add_argument("--undo", nargs="?", type=int, const=1, metavar="N",
                      help="undo the last N moves (default 1)")
    mode.add_argument("--print-config", action="store_true",
                      help="print effective configuration and exit")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    cfg = load_config(args.config)

    # Make sure a config file exists so it's easy to discover and edit. Do this
    # *before* applying transient CLI flags, so e.g. --dry-run is never baked
    # into the saved config.
    if not args.config.exists():
        save_config(cfg, args.config)

    if args.dry_run:
        cfg.dry_run = True

    if args.print_config:
        from .config import dumps_config
        print(dumps_config(cfg))
        return 0

    if args.undo is not None:
        for line in undo(args.undo):
            print(line)
        return 0

    if args.once:
        count = 0
        for entry in _top_level(Path(cfg.downloads_dir)):
            if is_eligible(entry, cfg, home=False):
                r = sort_file(entry, cfg)
                if r.action in ("moved", "dry-run", "duplicate"):
                    print(f"{r.action}: {r.src.name} → {r.category}")
                    count += 1
        print(f"Done — {count} file(s) {'previewed' if cfg.dry_run else 'sorted'}.")
        return 0

    if args.watch:
        import signal
        watcher = Watcher(cfg)
        # systemd stops the service with SIGTERM; exit the loop cleanly so the
        # lockfile is released by Watcher.run()'s finally block.
        signal.signal(signal.SIGTERM, lambda *_: watcher.stop())
        try:
            watcher.run()
        except SingleInstanceError as e:
            print(e, file=sys.stderr)
            return 1
        except KeyboardInterrupt:
            print("\nStopped.")
        return 0

    build_parser().print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
