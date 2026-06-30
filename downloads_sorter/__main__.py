"""Allow ``python3 -m downloads_sorter`` to run the CLI."""

from .cli import main

if __name__ == "__main__":
    raise SystemExit(main())
