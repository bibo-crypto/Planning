"""Fixes that came out of the external review report (each one reproduced first)."""
import os
import sqlite3
import zipfile
from datetime import datetime
from pathlib import Path

import openpyxl
import pandas as pd
import pytest


def _workbook(path: Path, sheets: dict[str, list[list]]) -> None:
    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in sheets.items():
        ws = wb.create_sheet(name)
        for row in rows:
            ws.append(row)
    wb.save(path)


# ------------------------------------------------------------ 1. atomic Excel save
def test_failed_save_leaves_the_original_workbook_untouched(tmp_path):
    from utility.excel_io import safe_save_workbook

    target = tmp_path / "orders.xlsx"
    _workbook(target, {"Orders": [["Partita Col"], ["A1"]]})
    original = target.read_bytes()

    class DiskFull:
        def save(self, destination):
            Path(destination).write_bytes(b"PK\x03\x04 half written")
            raise OSError(28, "No space left on device")

    with pytest.raises(OSError):
        safe_save_workbook(DiskFull(), target)
    assert target.read_bytes() == original
    assert [p.name for p in tmp_path.iterdir()] == ["orders.xlsx"]          # no temp file left behind


def test_garbage_written_without_an_error_is_never_swapped_in(tmp_path):
    from utility.excel_io import safe_save_workbook

    target = tmp_path / "orders.xlsx"
    _workbook(target, {"Orders": [["Partita Col"], ["A1"]]})
    original = target.read_bytes()

    class Garbage:
        def save(self, destination):
            Path(destination).write_bytes(b"not a workbook")

    with pytest.raises(RuntimeError, match="invalid workbook"):
        safe_save_workbook(Garbage(), target)
    assert target.read_bytes() == original


def test_locked_target_keeps_the_original_and_reports_it(tmp_path, monkeypatch):
    from utility import excel_io

    target = tmp_path / "orders.xlsx"
    _workbook(target, {"Orders": [["Partita Col"], ["A1"]]})
    original = target.read_bytes()
    monkeypatch.setattr(excel_io.os, "replace", lambda *_a: (_ for _ in ()).throw(PermissionError(13, "in use")))
    wb = openpyxl.Workbook()
    with pytest.raises(RuntimeError, match="open or locked"):
        excel_io.safe_save_workbook(wb, target)
    assert target.read_bytes() == original and [p.name for p in tmp_path.iterdir() if p.suffix == ".tmp"] == []


def test_successful_save_replaces_the_file_and_keeps_the_previous_version(tmp_path):
    from utility.excel_io import safe_save_workbook

    target = tmp_path / "orders.xlsx"
    _workbook(target, {"Orders": [["Partita Col"], ["OLD"]]})
    wb = openpyxl.Workbook()
    wb.active.append(["NEW"])
    safe_save_workbook(wb, target)
    assert openpyxl.load_workbook(target).active["A1"].value == "NEW"
    assert openpyxl.load_workbook(tmp_path / "orders.previous.xlsx")["Orders"]["A2"].value == "OLD"


def test_atomic_write_text_keeps_the_old_file_when_the_write_fails(tmp_path, monkeypatch):
    from utility import atomic

    target = tmp_path / "prefs.json"
    target.write_text("old", encoding="utf-8")
    monkeypatch.setattr(atomic.os, "replace", lambda *_a: (_ for _ in ()).throw(OSError("boom")))
    with pytest.raises(OSError):
        atomic.atomic_write_text(target, "new")
    assert target.read_text(encoding="utf-8") == "old" and [p.name for p in tmp_path.iterdir()] == ["prefs.json"]


# ------------------------------------------------------------ 3. parse_number
@pytest.mark.parametrize("value, expected", [
    (1.234, 1.234), (0.125, 0.125), (12.345, 12.345), (3, 3.0), ("12,5", 12.5), ("1,234.56", 1234.56),
    ("1.234,56", 1234.56), ("abc", None), (None, None), (float("nan"), None), (True, None),
])
def test_parse_number_treats_real_numbers_as_numbers(value, expected):
    from utility.utils import parse_number
    assert parse_number(value) == expected


# ------------------------------------------------------------ 2. archive before delete
@pytest.fixture
def history_db(tmp_path, monkeypatch):
    """orders_db functions bound to a throw-away database."""
    from utility import orders_db

    db = tmp_path / "history.sqlite3"
    real = {name: getattr(orders_db, name) for name in ("sync_rows", "archive", "reconcile_sheet")}
    monkeypatch.setattr(orders_db, "sync_rows", lambda p, s, rows: real["sync_rows"](p, s, rows, db_path=db))
    monkeypatch.setattr(orders_db, "archive", lambda p, s, cols, reason="deleted": real["archive"](p, s, cols, reason, db_path=db))
    monkeypatch.setattr(orders_db, "reconcile_sheet",
                        lambda p, s, keys, moved=None: real["reconcile_sheet"](p, s, keys, moved, db_path=db))
    return db


def test_delete_is_refused_when_the_history_cannot_be_written(tmp_path, monkeypatch):
    from exporters import biglietti_exporter
    from utility import orders_db

    path = tmp_path / "shared.xlsx"
    _workbook(path, {"PG-X": [["Partita Col", "Articolo"], ["A1", "C1"]], "Orders": [["Partita Col", "Articolo"]]})
    monkeypatch.setattr(orders_db, "archive", lambda *a, **k: (_ for _ in ()).throw(sqlite3.OperationalError("disk I/O error")))
    monkeypatch.setattr(orders_db, "sync_rows", lambda *a, **k: 0)
    with pytest.raises(RuntimeError, match="nothing was deleted"):
        biglietti_exporter.delete_pg_x_row(path, "A1")
    with pytest.raises(RuntimeError, match="nothing was deleted"):
        biglietti_exporter.delete_shipped_shared_rows(path, ["A1"], "PG-X")
    assert openpyxl.load_workbook(path)["PG-X"]["A2"].value == "A1"          # the row is still there


def test_delete_records_the_history_then_removes_the_row(tmp_path, history_db):
    from exporters import biglietti_exporter
    from utility import orders_db

    path = tmp_path / "shared.xlsx"
    _workbook(path, {"Orders": [["Partita Col", "Articolo"], ["B2", "C2"]], "PG-X": [["Partita Col", "Articolo"]]})
    assert biglietti_exporter.delete_shipped_shared_rows(path, ["B2"], "Orders") == 1
    shipped = orders_db.list_shipped(history_db)
    assert [r["partita_col"] for r in shipped] == ["b2"] and shipped[0]["archived_reason"] == "shipped/invoiced"
    assert openpyxl.load_workbook(path)["Orders"].max_row == 1


# ------------------------------------------------------------ 5. PG-X -> Orders history
def test_moving_a_row_to_orders_closes_its_pgx_history_record(tmp_path, history_db):
    from exporters import biglietti_exporter
    from utility import orders_db

    path = tmp_path / "shared.xlsx"
    _workbook(path, {"PG-X": [["Partita Col", "Articolo"], ["A1", "C1"]], "Orders": [["Partita Col", "Articolo"]]})
    wb = openpyxl.load_workbook(path)
    biglietti_exporter._sync_workbook_history(path, wb)
    assert {r["sheet_name"] for r in orders_db.list_open(history_db)} == {"PG-X"}

    assert biglietti_exporter.move_pg_x_to_orders(path, "A1") == 1
    open_rows = orders_db.list_open(history_db)
    assert [(r["sheet_name"], r["partita_col"]) for r in open_rows] == [("Orders", "a1")]
    archived = [r for r in orders_db.list_history(history_db) if r["status"] == "archived"]
    assert [(r["sheet_name"], r["archived_reason"]) for r in archived] == [("PG-X", "moved to Orders")]


def test_history_is_not_pruned_when_the_sheet_has_no_partita_col_column(tmp_path, history_db):
    from exporters import biglietti_exporter
    from utility import orders_db

    path = tmp_path / "shared.xlsx"
    _workbook(path, {"Orders": [["Partita Col"], ["A1"]]})
    biglietti_exporter._sync_workbook_history(path, openpyxl.load_workbook(path))
    _workbook(path, {"Orders": [["Something else"], ["A1"]]})
    biglietti_exporter._sync_workbook_history(path, openpyxl.load_workbook(path))
    assert len(orders_db.list_open(history_db)) == 1


# ------------------------------------------------------------ 4 + 6. machines
def test_machine_validation_rules():
    from utility.master_data import validate_machine

    existing = [{"code": "3300", "number": "4", "rocche": "672"}, {"code": "3301", "number": "11", "rocche": "6"}]
    assert validate_machine({"code": "3311", "number": "13", "rocche": "100"}, existing) is None
    assert "Number" in validate_machine({"code": "3311", "number": "abc", "rocche": "100"}, existing)
    assert "Rocche" in validate_machine({"code": "3311", "number": "13", "rocche": "0"}, existing)
    assert "Rocche" in validate_machine({"code": "3311", "number": "13", "rocche": "-5"}, existing)
    assert "already used" in validate_machine({"code": "3311", "number": "4", "rocche": "100"}, existing)
    assert "already used" in validate_machine({"code": "3300", "number": "13", "rocche": "100"}, existing)
    assert validate_machine({"code": "3300", "number": "4", "rocche": "700"}, existing, editing_index=0) is None  # editing itself


def test_bad_machine_rows_never_stop_the_constants_from_loading(tmp_path, monkeypatch):
    from calculate import constants
    from utility import master_data

    monkeypatch.setattr(master_data, "PATH", tmp_path / "master_data.json")
    master_data.PATH.write_text('{"machines": [{"code": "3300", "number": "abc", "rocche": "672"},'
                                ' {"code": "3301", "number": "11", "rocche": "6"}]}', encoding="utf-8")
    try:
        constants.reload_machines()                        # used to raise ValueError
        assert constants.MACHINE_CAPACITY_BY_NUMBER[11] == 6 and 4 in constants.MACHINE_CAPACITY_BY_NUMBER
    finally:
        monkeypatch.undo()
        constants.reload_machines()


def test_saving_a_new_machine_capacity_reaches_the_calculations_without_a_restart(tmp_path, monkeypatch):
    from calculate import abbina_calculator, abbina_suggestions, constants
    from exporters import biglietti_exporter
    from pipelines import ordine_med
    from utility import master_data

    monkeypatch.setattr(master_data, "PATH", tmp_path / "master_data.json")
    data = master_data.load()
    try:
        for machine in data["machines"]:
            if machine["number"] == "7":
                assert machine["rocche"] == "72"
                machine["rocche"] = "80"
        master_data.save(data)
        assert constants.MACHINE_CAPACITY_BY_NUMBER[7] == 80
        assert 80 in abbina_calculator.MACHINE_CAPACITIES and 72 not in abbina_calculator.MACHINE_CAPACITIES
        assert abbina_calculator._smallest_fitting_machine(75) == 80
        assert abbina_suggestions.MACHINE_NUMBERS[80] == 7
        assert biglietti_exporter.MACHINE_SIZE_TABLE[80] == 7
        assert ordine_med.GRUPPO_MACCHINA_TABLE[80] == 3307
    finally:
        monkeypatch.undo()
        constants.reload_machines()
    assert 72 in abbina_calculator.MACHINE_CAPACITIES and 80 not in abbina_calculator.MACHINE_CAPACITIES


# ------------------------------------------------------------ 7. stock grouping
def test_stock_with_the_same_partita_in_two_articles_is_not_merged():
    from calculate.magazino import summarize_by_partita

    frame = pd.DataFrame([
        {"articolo": "G1", "titolo": "30/1", "partita": "P1", "colli": 10, "esistenza": 5.0},
        {"articolo": "G2", "titolo": "40/1", "partita": "P1", "colli": 20, "esistenza": 9.0},
        {"articolo": "G1", "titolo": "30/1", "partita": "P1", "colli": 2, "esistenza": 1.0},
    ])
    out = summarize_by_partita(frame).set_index("articolo")
    assert len(out) == 2
    assert (out.loc["G1", "mag_rocche"], out.loc["G2", "mag_rocche"]) == (12, 20)


# ------------------------------------------------------------ 8. disk cache
def test_cache_file_names_are_valid_on_windows_and_do_not_collide(tmp_path, monkeypatch):
    from utility import disk_cache

    monkeypatch.setattr(disk_cache, "APP_DATA_DIR", tmp_path)
    key = ("file.xlsx", 1, 2)
    first = disk_cache._cache_path("magazino:None", key)
    second = disk_cache._cache_path("magazino:('G130', 'G170')", key)
    assert first != second
    for path in (first, second):
        assert not set(':*?"<>|') & set(path.name)


def test_disk_cache_really_writes_a_file_and_hands_out_private_copies(tmp_path, monkeypatch):
    from utility import disk_cache

    monkeypatch.setattr(disk_cache, "APP_DATA_DIR", tmp_path / "app")
    source = tmp_path / "stock.xlsx"
    source.write_text("x", encoding="utf-8")
    disk_cache.invalidate()
    calls = []

    def compute():
        calls.append(1)
        return pd.DataFrame({"a": [1, 2]}), []

    first, _ = disk_cache.cached_load("magazino:None", source, compute)
    assert list((tmp_path / "app" / "cache").glob("*.pkl"))                      # the disk copy exists now
    first.loc[0, "a"] = 999                                                       # the caller edits its copy ...
    second, _ = disk_cache.cached_load("magazino:None", source, compute)
    assert second.loc[0, "a"] == 1 and len(calls) == 1                           # ... the cache is unaffected
    disk_cache.invalidate()
    third, _ = disk_cache.cached_load("magazino:None", source, compute)          # served from the disk file
    assert third.loc[0, "a"] == 1 and len(calls) == 1


# ------------------------------------------------------------ backups
def test_backup_skips_dev_folders_and_snapshots_sqlite(tmp_path, monkeypatch):
    from utility import backup

    app = tmp_path / "app"
    (app / "data").mkdir(parents=True)
    (app / "venv" / "lib").mkdir(parents=True)
    (app / "venv" / "lib" / "big.py").write_text("x", encoding="utf-8")
    (app / "settings").mkdir()
    (app / "settings" / "prefs.json").write_text("{}", encoding="utf-8")
    db = app / "data" / "orders.sqlite3"
    conn = sqlite3.connect(db)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("CREATE TABLE t(x)")
    conn.execute("INSERT INTO t VALUES (42)")
    conn.commit()                                  # the row is in the -wal file, not yet in the main file
    monkeypatch.setattr(backup, "APP_DATA_DIR", app)
    try:
        archive_path = backup.create_backup(tmp_path / "planning_backup_test.zip")
    finally:
        conn.close()
    with zipfile.ZipFile(archive_path) as archive:
        names = set(archive.namelist())
        assert "settings/prefs.json" in names and "data/orders.sqlite3" in names
        assert not any(n.startswith("venv/") or n.endswith(("-wal", "-shm")) for n in names)
        archive.extract("data/orders.sqlite3", tmp_path / "out")
    assert sqlite3.connect(tmp_path / "out" / "data" / "orders.sqlite3").execute("SELECT x FROM t").fetchall() == [(42,)]


def test_restore_removes_stale_wal_files_of_the_replaced_database(tmp_path, monkeypatch):
    from utility import backup

    app = tmp_path / "app"
    (app / "data").mkdir(parents=True)
    (app / "data" / "orders.sqlite3-wal").write_bytes(b"stale wal")
    (app / "data" / "orders.sqlite3-shm").write_bytes(b"stale shm")
    zip_path = tmp_path / "b.zip"
    good = tmp_path / "good.sqlite3"
    sqlite3.connect(good).execute("CREATE TABLE t(x)").connection.commit()
    with zipfile.ZipFile(zip_path, "w") as archive:
        archive.write(good, "data/orders.sqlite3")
    monkeypatch.setattr(backup, "APP_DATA_DIR", app)
    assert backup.restore_backup(zip_path) == 1
    assert not (app / "data" / "orders.sqlite3-wal").exists() and not (app / "data" / "orders.sqlite3-shm").exists()


# ------------------------------------------------------------ build environment
def test_venv_prune_keeps_dev_tools_and_their_dependencies():
    import sync_venv_packages as sync

    kept = sync._with_dependencies({"pytest"})
    assert {"pytest", "pluggy", "iniconfig"} <= kept


# ------------------------------------------------------------ one writer at a time
def test_shared_workbook_writers_never_run_at_the_same_time():
    import threading
    import time

    from exporters.biglietti_exporter import _serialized_workbook_write

    active, overlaps = [], []

    @_serialized_workbook_write
    def writer():
        active.append(1)
        if len(active) > 1:
            overlaps.append(1)
        time.sleep(0.02)
        active.pop()

    threads = [threading.Thread(target=writer) for _ in range(6)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert overlaps == []
