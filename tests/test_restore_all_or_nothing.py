"""restore_backup replaces files all or nothing.

Before: the files were copied one by one over the live ones, so a failure on the second file left the first one
already replaced (a mixture of old and restored data).  Now every file is staged next to its target first and the
swaps are rolled back when one fails.
"""
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

from utility import backup


@pytest.fixture
def app_data(tmp_path, monkeypatch):
    data = tmp_path / "appdata"
    data.mkdir()
    monkeypatch.setattr(backup, "APP_DATA_DIR", data)
    return data


def make_backup(tmp_path, files):
    archive = tmp_path / "planning_backup_test.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return archive


def snapshot(root):
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def populate(data):
    (data / "a.txt").write_text("old A", encoding="utf-8")
    (data / "b.txt").write_text("old B", encoding="utf-8")
    (data / "c.txt").write_text("old C", encoding="utf-8")


BACKUP = {"a.txt": "new A", "b.txt": "new B", "c.txt": "new C", "sub/d.txt": "new D"}


def test_a_normal_restore_replaces_everything_and_leaves_no_temporary_files(app_data, tmp_path):
    populate(app_data)
    assert backup.restore_backup(make_backup(tmp_path, BACKUP)) == 4
    assert snapshot(app_data) == {"a.txt": b"new A", "b.txt": b"new B", "c.txt": b"new C", "sub/d.txt": b"new D"}


def test_a_failure_while_swapping_the_second_file_puts_every_file_back(app_data, tmp_path, monkeypatch):
    populate(app_data)
    before = snapshot(app_data)
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst).name == "b.txt" and str(src).endswith(backup._RESTORE_NEW_SUFFIX):
            raise PermissionError(13, "Access is denied (simulated: antivirus holds b.txt)")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup.os, "replace", failing_replace)
    with pytest.raises(PermissionError):
        backup.restore_backup(make_backup(tmp_path, BACKUP))

    assert snapshot(app_data) == before          # a.txt is old again (it had already been swapped), no leftovers anywhere


def test_a_failure_while_copying_the_second_file_replaces_nothing(app_data, tmp_path, monkeypatch):
    populate(app_data)
    before = snapshot(app_data)
    real_copy = backup.shutil.copy2

    def failing_copy(src, dst, *args, **kwargs):
        if Path(dst).name.startswith("b.txt"):
            Path(dst).write_bytes(b"half")       # a half-written staged copy
            raise OSError(28, "No space left on device (simulated)")
        return real_copy(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup.shutil, "copy2", failing_copy)
    with pytest.raises(OSError, match="No space"):
        backup.restore_backup(make_backup(tmp_path, BACKUP))

    assert snapshot(app_data) == before


def test_a_failed_restore_keeps_the_database_and_its_wal_files_as_they_were(app_data, tmp_path, monkeypatch):
    db = app_data / "orders.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE t (x)")
    conn.execute("INSERT INTO t VALUES (1)")
    conn.commit()
    conn.close()
    wal, shm = Path(str(db) + "-wal"), Path(str(db) + "-shm")
    wal.write_bytes(b"wal-bytes")
    shm.write_bytes(b"shm-bytes")
    (app_data / "z.txt").write_text("old Z", encoding="utf-8")
    before = snapshot(app_data)

    new_db = tmp_path / "new.sqlite3"
    other = sqlite3.connect(new_db)
    other.execute("CREATE TABLE t (x)")
    other.execute("INSERT INTO t VALUES (2)")
    other.commit()
    other.close()
    archive = make_backup(tmp_path, {"orders.sqlite3": new_db.read_bytes(), "z.txt": "new Z"})

    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst).name == "z.txt" and str(src).endswith(backup._RESTORE_NEW_SUFFIX):
            raise PermissionError(13, "Access is denied (simulated)")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup.os, "replace", failing_replace)
    with pytest.raises(PermissionError):
        backup.restore_backup(archive)

    assert snapshot(app_data) == before          # the database, its -wal and -shm and z.txt: byte for byte as before
    check = sqlite3.connect(f"file:{db.as_posix()}?mode=ro&immutable=1", uri=True)
    assert check.execute("SELECT x FROM t").fetchone()[0] == 1
    check.close()


def test_a_restore_into_a_fresh_folder_that_fails_leaves_no_new_files(app_data, tmp_path, monkeypatch):
    real_replace = os.replace

    def failing_replace(src, dst, *args, **kwargs):
        if Path(dst).name == "b.txt" and str(src).endswith(backup._RESTORE_NEW_SUFFIX):
            raise PermissionError(13, "simulated")
        return real_replace(src, dst, *args, **kwargs)

    monkeypatch.setattr(backup.os, "replace", failing_replace)
    with pytest.raises(PermissionError):
        backup.restore_backup(make_backup(tmp_path, {"a.txt": "A", "b.txt": "B"}))

    assert snapshot(app_data) == {}              # a.txt had been installed first: it is removed again
