"""A hung start leaves evidence on disk; a normal start leaves nothing; backup/cache failures are logged."""
import time

import pytest

from gui import gui as gui_module
from gui.gui import ConverterApp
from utility import backup, prezzi_db

from tests.test_startup_pages import start_app  # noqa: F401  (fixture)


def test_a_slow_start_writes_the_stack_of_every_thread_and_a_finished_start_removes_the_file(start_app, monkeypatch):
    monkeypatch.setattr(ConverterApp, "STARTUP_WATCHDOG_SECONDS", 1)
    real_build = ConverterApp._build_ui
    seen = {}

    def slow_build(self):                     # stands in for a page that blocks the main thread
        time.sleep(2.6)
        seen["text"] = self._hang_dump_path.read_text(encoding="utf-8")
        real_build(self)

    monkeypatch.setattr(ConverterApp, "_build_ui", slow_build)
    app, errors, shown = start_app()
    assert errors == []
    assert "were not built 1s after the start" in seen["text"]
    assert "slow_build" in seen["text"]       # the dump names the function the main thread was stuck in
    assert seen["text"].count("most recent call first") >= 2        # repeated: shows whether it moves
    assert not app._hang_dump_path.exists()   # the pages were built in the end -> no leftover evidence


def test_a_normal_start_leaves_no_hang_file(start_app):
    app, errors, shown = start_app()
    assert errors == [] and not app._hang_dump_path.exists()


def test_a_failed_snapshot_is_logged_and_the_plain_file_is_still_backed_up(tmp_path, caplog):
    fake = tmp_path / "broken.db"
    fake.write_bytes(b"not a database" * 20)
    with caplog.at_level("WARNING", logger="converter"):
        assert backup._snapshot_sqlite(fake, tmp_path / "copy.db") is False
    assert any("consistent SQLite snapshot" in r.getMessage() for r in caplog.records)


def test_a_failing_daily_backup_is_logged_not_silent(tmp_path, monkeypatch, caplog):
    def boom(_destination):
        raise OSError("disk full")
    monkeypatch.setattr(backup, "create_backup", boom)
    with caplog.at_level("WARNING", logger="converter"):
        assert backup.daily_backup(tmp_path / "backups") is None
    assert any("daily backup failed" in r.getMessage() for r in caplog.records)


def test_a_damaged_listini_cache_is_logged_and_treated_as_missing(tmp_path, caplog):
    bad = tmp_path / "prezzi.sqlite3"
    bad.write_bytes(b"garbage" * 100)
    with caplog.at_level("WARNING", logger="converter"):
        assert prezzi_db.load_prezzi_frame(("x",), db_path=bad) is None
    assert any("Listini cache could not be read" in r.getMessage() for r in caplog.records)
