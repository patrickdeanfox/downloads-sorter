"""Watcher tests, with emphasis on the nested Downloads-inside-home case.

These drive `_tick()` directly (two ticks: first registers the file, second
moves it once it is size-stable) instead of running the real loop.
"""

from pathlib import Path

from downloads_sorter import core
from downloads_sorter.config import Config
from downloads_sorter.watcher import Watcher


def _make_cfg(home: Path) -> Config:
    return Config(
        home_dir=str(home),
        downloads_dir=str(home / "Downloads"),
        watch_home=True,
        notifications=False,
        settle_seconds=0.0,   # any age counts as "finished"
        sort_existing_on_start=False,
    )


def test_downloads_inside_home_still_sorts(tmp_path, monkeypatch):
    """Regression: when Downloads is a child of home, the home scan must not
    wipe the Downloads file's pending state (prefix-match bug)."""
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "state" / "moves.log")
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    cfg = _make_cfg(home)

    w = Watcher(cfg)
    w._seed_home_ignore()                      # snapshot existing home entries

    f = home / "Downloads" / "new.pdf"
    f.write_text("data")

    w._tick()                                  # tick 1: register (size now known)
    assert f.exists()                          # not moved yet
    w._tick()                                  # tick 2: size stable → move
    assert not f.exists()
    assert (home / "Downloads" / "Documents" / "new.pdf").exists()


def test_new_home_file_moves_but_preexisting_is_ignored(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    cfg = _make_cfg(home)

    preexisting = home / "old.pdf"; preexisting.write_text("old")
    w = Watcher(cfg)
    w._seed_home_ignore()                      # snapshots old.pdf → ignored forever

    newfile = home / "fresh.pdf"; newfile.write_text("new")
    w._tick(); w._tick()

    assert preexisting.exists()                # never swept
    assert not newfile.exists()                # new arrival moved
    assert (home / "Downloads" / "Documents" / "fresh.pdf").exists()


def test_unknown_type_in_home_left_alone(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    home = tmp_path / "home"
    (home / "Downloads").mkdir(parents=True)
    cfg = _make_cfg(home)
    w = Watcher(cfg); w._seed_home_ignore()

    log = home / "scratch.log"; log.write_text("x")   # unknown type
    w._tick(); w._tick()
    assert log.exists()                               # home: known types only
