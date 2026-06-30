"""CLI-level tests, focused on config persistence side-effects."""

from downloads_sorter import cli
from downloads_sorter.config import load_config


def test_dry_run_flag_not_persisted_to_saved_config(tmp_path):
    """--dry-run must never be baked into the auto-created config file.

    Regression: the default config was once saved *after* applying the
    --dry-run override, leaving dry_run=true on disk so the next plain run
    silently stayed in preview mode.
    """
    cfg_path = tmp_path / "config.toml"
    assert not cfg_path.exists()

    rc = cli.main(["--print-config", "--dry-run", "--config", str(cfg_path)])
    assert rc == 0
    assert cfg_path.exists()

    on_disk = load_config(cfg_path)
    assert on_disk.dry_run is False


def test_print_config_does_not_overwrite_existing(tmp_path):
    cfg_path = tmp_path / "config.toml"
    cfg_path.write_text('downloads_dir = "/custom/dl"\ndry_run = false\n')
    cli.main(["--print-config", "--config", str(cfg_path)])
    assert load_config(cfg_path).downloads_dir == "/custom/dl"
