"""Unit tests for the pure sorting logic and config round-trip.

Run with: pytest  (no network, no services, fully isolated via tmp_path)
"""

import tomllib

import pytest

from downloads_sorter import config as cfgmod
from downloads_sorter import core
from downloads_sorter.config import Config


# ── name / category ─────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name, stem, suffix", [
    ("report.pdf", "report", ".pdf"),
    ("archive.tar.gz", "archive", ".tar.gz"),
    ("no_extension", "no_extension", ""),
    (".hidden", ".hidden", ""),          # leading dot is part of the stem here
    ("a.b.c.txt", "a.b.c", ".txt"),
])
def test_split_name(name, stem, suffix):
    assert core.split_name(name) == (stem, suffix)


def test_categorize_uses_compound_suffix():
    em = Config().ext_map()
    assert core.categorize("backup.tar.gz", em) == "Archives"
    assert core.categorize("photo.JPG", em) == "Images"
    assert core.categorize("mystery.qzx", em) == "Misc"


@pytest.mark.parametrize("name, partial", [
    ("file.crdownload", True),
    ("file.part", True),
    ("file.txt", False),
    ("backup~", True),
])
def test_is_partial(name, partial):
    assert core.is_partial(name, cfgmod.DEFAULT_SKIP_SUFFIXES) is partial


# ── eligibility ─────────────────────────────────────────────────────────────────

def test_home_skips_unknown_types(tmp_path):
    cfg = Config(downloads_dir=str(tmp_path))
    known = tmp_path / "doc.pdf"; known.write_text("x")
    unknown = tmp_path / "notes.xyz"; unknown.write_text("x")
    assert core.is_eligible(known, cfg, home=True) is True
    assert core.is_eligible(unknown, cfg, home=True) is False
    # In Downloads, unknown types are still eligible (they go to Misc).
    assert core.is_eligible(unknown, cfg, home=False) is True


def test_dotfiles_and_partials_never_eligible(tmp_path):
    cfg = Config(downloads_dir=str(tmp_path))
    dot = tmp_path / ".secret.pdf"; dot.write_text("x")
    part = tmp_path / "big.iso.part"; part.write_text("x")
    assert core.is_eligible(dot, cfg, home=False) is False
    assert core.is_eligible(part, cfg, home=False) is False


# ── moving ──────────────────────────────────────────────────────────────────────

def test_sort_file_moves_into_category(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "state" / "moves.log")
    dl = tmp_path / "Downloads"; dl.mkdir()
    cfg = Config(downloads_dir=str(dl))
    src = dl / "invoice.pdf"; src.write_text("hello")

    res = core.sort_file(src, cfg)
    assert res.action == "moved"
    assert res.dest == dl / "Documents" / "invoice.pdf"
    assert res.dest.exists() and not src.exists()


def test_collision_uniquifies(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    dl = tmp_path / "Downloads"; dl.mkdir()
    cfg = Config(downloads_dir=str(dl))
    (dl / "Documents").mkdir()
    (dl / "Documents" / "a.txt").write_text("ALREADY")   # different content
    src = dl / "a.txt"; src.write_text("NEW")

    res = core.sort_file(src, cfg)
    assert res.action == "moved"
    assert res.dest == dl / "Documents" / "a-1.txt"


def test_identical_duplicate_moved_to_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    dl = tmp_path / "Downloads"; dl.mkdir()
    cfg = Config(downloads_dir=str(dl))
    (dl / "Documents").mkdir()
    (dl / "Documents" / "a.txt").write_text("SAME")
    src = dl / "a.txt"; src.write_text("SAME")

    res = core.sort_file(src, cfg)
    assert res.action == "duplicate"
    assert res.dest.parent.name == "Duplicates"
    assert not src.exists()


def test_dry_run_does_not_move(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    dl = tmp_path / "Downloads"; dl.mkdir()
    cfg = Config(downloads_dir=str(dl), dry_run=True)
    src = dl / "song.mp3"; src.write_text("x")

    res = core.sort_file(src, cfg)
    assert res.action == "dry-run"
    assert src.exists()
    assert not (dl / "Media" / "song.mp3").exists()


def test_undo_restores_file(tmp_path, monkeypatch):
    monkeypatch.setattr(core, "MOVES_LOG", tmp_path / "moves.log")
    dl = tmp_path / "Downloads"; dl.mkdir()
    cfg = Config(downloads_dir=str(dl))
    src = dl / "photo.png"; src.write_text("img")

    res = core.sort_file(src, cfg)
    assert res.dest.exists()
    lines = core.undo(1)
    assert any("restored" in ln for ln in lines)
    assert src.exists() and not res.dest.exists()


# ── config round-trip ───────────────────────────────────────────────────────────

def test_config_toml_roundtrip(tmp_path):
    cfg = Config(downloads_dir="/tmp/dl", watch_home=False, poll_interval=3.5,
                 sorted_subfolder="Sorted")
    text = cfgmod.dumps_config(cfg)
    # Must be valid TOML.
    parsed = tomllib.loads(text)
    assert parsed["downloads_dir"] == "/tmp/dl"
    assert parsed["watch_home"] is False
    assert parsed["poll_interval"] == 3.5
    assert parsed["folders"]["Documents"]

    # And load_config must reconstruct an equivalent Config.
    path = tmp_path / "config.toml"
    cfgmod.save_config(cfg, path)
    loaded = cfgmod.load_config(path)
    assert loaded.downloads_dir == "/tmp/dl"
    assert loaded.watch_home is False
    assert loaded.poll_interval == 3.5
    assert loaded.sorted_subfolder == "Sorted"
    assert loaded.output_base.name == "Sorted"
