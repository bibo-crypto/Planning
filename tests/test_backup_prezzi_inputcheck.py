"""Daily database backup, Prezzi Ordine Med numbering, and the pre-convert input check."""
import sqlite3
from datetime import date, timedelta

import openpyxl
import pytest

from exporters import input_check
from pipelines.ordine_med import next_prezzi_path
from utility import db_backup


@pytest.fixture
def dbs(tmp_path, monkeypatch):
    paths = {"dyeing_tracker": tmp_path / "live" / "dyeing_tracker.db",
             "planning_orders": tmp_path / "live" / "planning_orders.sqlite3"}
    for path in paths.values():
        path.parent.mkdir(exist_ok=True)
        conn = sqlite3.connect(path)
        conn.execute("create table t(v)"); conn.execute("insert into t values ('original')")
        conn.commit(); conn.close()
    monkeypatch.setattr(db_backup, "BACKUP_DIR", tmp_path / "backups")
    monkeypatch.setattr(db_backup, "databases",
                        lambda: [db_backup.Database(n, p) for n, p in paths.items()])
    return paths


def _value(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("select v from t").fetchone()[0]
    finally:
        conn.close()


def test_backup_once_a_day_and_keep_only_ten_days(dbs):
    today = date(2026, 11, 2)
    assert len(db_backup.create_backup(today=today)) == 2
    assert db_backup.create_backup(today=today) == []                 # already done today
    for back in range(1, 14):                                         # 13 older days
        db_backup.create_backup(today=today - timedelta(days=back))
    days = {d for name, d, _ in db_backup.list_backups() if name == "dyeing_tracker"}
    assert len(days) == db_backup.KEEP_DAYS and today in days
    assert min(days) == today - timedelta(days=9)


def test_restore_puts_back_the_data_and_keeps_a_safety_copy(dbs):
    db_backup.create_backup(today=date(2026, 11, 1))
    conn = sqlite3.connect(dbs["dyeing_tracker"]); conn.execute("update t set v='changed'"); conn.commit(); conn.close()
    backup = next(p for n, _d, p in db_backup.list_backups() if n == "dyeing_tracker")
    safety = db_backup.restore_backup(backup)
    assert _value(dbs["dyeing_tracker"]) == "original" and _value(safety) == "changed"
    with pytest.raises(ValueError):
        db_backup.restore_backup(dbs["dyeing_tracker"])               # not a dated backup file


def test_prezzi_ordine_med_gets_the_next_number(tmp_path):
    assert next_prezzi_path(tmp_path).name == "Prezzi Ordine Med 1.xlsx"
    (tmp_path / "Prezzi Ordine Med 1.xlsx").touch(); (tmp_path / "Prezzi Ordine Med 4.xlsx").touch()
    assert next_prezzi_path(tmp_path).name == "Prezzi Ordine Med 5.xlsx"


def _book(path, sheet, headers):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = sheet
    ws.append(headers); ws.append(["x"] * len(headers)); wb.save(path)


def test_input_check_names_missing_columns(tmp_path):
    full = tmp_path / "med.xlsx"
    _book(full, "ORDINE", list(input_check.MED_ORDER_COLUMNS))
    assert input_check.check_med_input(full) == []
    partial = tmp_path / "med2.xlsx"
    _book(partial, "ORDINE", ["ARTICOLO", "COLORE", "ROCC", "ABBIN", "CONSEGNA", "PT GRG"])
    (problem,) = input_check.check_med_input(partial)
    assert "TITOLO" in problem and "DESCR COL" in problem


def test_input_check_for_biglietti_order_file(tmp_path):
    path = tmp_path / "erp.xlsx"
    _book(path, "Sheet1", ["Cliente", "Articolo", "Colore", "Ordine", "Riga", "Partita", "Ordinata", "Consegna"])
    problems = input_check.check_order_file("elvy", path)
    assert any("Descrizione aggiuntiva ordine" in p for p in problems)
    assert any("Dispo-Bagno" in p for p in problems)
    assert input_check.check_order_file("elvy", tmp_path / "missing.xlsx") == []   # unreadable: left to the loader
