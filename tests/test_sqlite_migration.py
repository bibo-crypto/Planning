"""Situazione database: creating it, upgrading an older one in place, and what a failed upgrade must not do."""
import sqlite3

import pytest

from utility import situazione_db

ADDED_COLUMNS = {
    "source_snapshot": ("data_fingerprint", "column_meta", "payload_json"),
    "partita_state": ("custom", "ritardo_consegna", "prezzo"),
    "upload_log": ("file_path",),
}


@pytest.fixture()
def db(tmp_path, monkeypatch):
    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "dyeing_tracker.db"))
    return tmp_path / "dyeing_tracker.db"


def _columns(path, table):
    conn = sqlite3.connect(path)
    try:
        return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
    finally:
        conn.close()


def _make_legacy(path):
    """A database as an older release left it: same tables, without the columns added later."""
    situazione_db.init_db()
    conn = sqlite3.connect(path)
    try:
        conn.execute("INSERT INTO partita_state (partita, new_comment) VALUES ('P1', 'keep me')")
        conn.execute("INSERT INTO upload_log (source_name, file_name, row_count, status) VALUES ('dfm', 'old.xlsx', 7, 'ok')")
        conn.execute("INSERT INTO codes (articolo_filato, titolo) VALUES ('A1', '30/1')")
        conn.commit()
        for table, columns in ADDED_COLUMNS.items():
            for column in columns:
                conn.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
        conn.commit()
    finally:
        conn.close()


def test_a_fresh_database_gets_every_table_and_column(db):
    situazione_db.init_db()
    for table, columns in ADDED_COLUMNS.items():
        assert set(columns) <= _columns(db, table)


def test_an_older_database_is_upgraded_without_losing_a_record(db):
    _make_legacy(db)
    for table, columns in ADDED_COLUMNS.items():
        assert not set(columns) & _columns(db, table)          # really an old layout
    situazione_db.init_db()
    for table, columns in ADDED_COLUMNS.items():
        assert set(columns) <= _columns(db, table)
    assert situazione_db.get_all_states()["P1"]["new_comment"] == "keep me"
    assert situazione_db.get_upload("dfm")["row_count"] == 7
    assert situazione_db.load_codes() == {"A1": "30/1"}


def test_upgrading_twice_changes_nothing_and_duplicates_nothing(db):
    _make_legacy(db)
    situazione_db.init_db()
    states, uploads, codes = situazione_db.get_all_states(), situazione_db.get_all_uploads(), situazione_db.load_codes()
    situazione_db.init_db()
    assert (situazione_db.get_all_states(), situazione_db.get_all_uploads(), situazione_db.load_codes()) == (states, uploads, codes)
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM partita_state").fetchone()[0] == 1
    finally:
        conn.close()


def test_a_corrupted_database_file_raises_and_is_left_untouched(db):
    db.write_bytes(b"this is not a sqlite database " * 50)
    before = db.read_bytes()
    with pytest.raises(sqlite3.DatabaseError):
        situazione_db.init_db()
    assert db.read_bytes() == before            # never "repaired" by deleting the user's file


def test_a_failed_upgrade_is_reported_not_swallowed(db, monkeypatch):
    """Was finding F1: every OperationalError of an ALTER was taken for 'column already exists'."""
    _make_legacy(db)
    real_connect = sqlite3.connect

    def read_only(_path, *args, **kwargs):
        conn = real_connect(f"file:{db.as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        return conn

    monkeypatch.setattr(situazione_db.sqlite3, "connect", read_only)
    with pytest.raises(sqlite3.OperationalError):
        situazione_db.init_db()


def test_a_missing_column_is_added_once_and_a_concurrent_duplicate_is_tolerated(db, monkeypatch):
    _make_legacy(db)
    conn = sqlite3.connect(db)
    try:
        real = situazione_db._add_column_if_missing
        # another process added the column between the check and the ALTER: only that error is ignored
        conn.execute("ALTER TABLE partita_state ADD COLUMN prezzo TEXT")
        conn.commit()
        monkeypatch.setattr(situazione_db, "_LATER_COLUMNS", (("partita_state", "prezzo"),))
        real(conn, "partita_state", "prezzo")                     # already there: nothing happens, no error
    finally:
        conn.close()


def _fail_then_work(monkeypatch, message, failures):
    real = situazione_db._init_db_once
    calls = {"n": 0}

    def flaky():
        calls["n"] += 1
        if calls["n"] <= failures:
            raise sqlite3.OperationalError(message)
        real()

    monkeypatch.setattr(situazione_db, "_init_db_once", flaky)
    monkeypatch.setattr(situazione_db.time, "sleep", lambda _s: None)
    return calls


def test_a_transient_disk_io_error_at_start_is_retried(db, monkeypatch, caplog):
    calls = _fail_then_work(monkeypatch, "disk I/O error", failures=2)
    with caplog.at_level("WARNING", logger="converter"):
        situazione_db.init_db()
    assert calls["n"] == 3 and "ALTER" not in caplog.text
    assert sum("Database init attempt" in r.getMessage() for r in caplog.records) == 2
    assert set(ADDED_COLUMNS["partita_state"]) <= _columns(db, "partita_state")


def test_a_lasting_lock_is_raised_after_three_attempts(db, monkeypatch):
    calls = _fail_then_work(monkeypatch, "database is locked", failures=99)
    with pytest.raises(sqlite3.OperationalError, match="locked"):
        situazione_db.init_db()
    assert calls["n"] == 3


def test_a_non_transient_error_is_raised_at_once_without_retry(db, monkeypatch):
    calls = _fail_then_work(monkeypatch, "attempt to write a readonly database", failures=99)
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        situazione_db.init_db()
    assert calls["n"] == 1
