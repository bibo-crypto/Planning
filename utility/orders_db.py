"""Persistent order history for Create (EXCEL+Biglietti).

The shared workbook remains the operational exchange file. SQLite is the
append-safe history: rows are upserted as open and are archived before a
workbook deletion, so invoices/shipped colors remain searchable historically.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Any

from utility.utils import APP_DATA_DIR

DB_PATH = APP_DATA_DIR / "data" / "planning_orders.sqlite3"


def _connect(path: Path = DB_PATH) -> sqlite3.Connection:
    """Open the orders SQLite database (creating the folder and the orders table when missing) with rows accessible by name."""
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        source_file TEXT NOT NULL,
        sheet_name TEXT NOT NULL,
        partita_col TEXT NOT NULL,
        order_json TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'open',
        archived_reason TEXT,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL,
        archived_at TEXT
    )""")
    conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_orders_key ON orders(source_file, sheet_name, partita_col)")
    conn.commit()
    return conn


def _key(value: Any) -> str:
    text = str(value or "").strip()
    try:
        number = float(text.replace(",", "."))
        return str(int(number)) if number.is_integer() else str(number)
    except ValueError:
        return text.casefold()


def sync_rows(source_file: Path, sheet_name: str, rows: Iterable[dict[str, Any]], db_path: Path = DB_PATH) -> int:
    """Mirror the rows of a shared-Excel sheet into SQLite, keyed by (file, sheet, Partita Col); an existing row is updated and re-opened.
    Returns how many rows were written.
    """
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    count = 0
    try:
        for row in rows:
            partita_col = _key(row.get("Partita Col"))
            if not partita_col:
                continue
            payload = json.dumps(row, ensure_ascii=False, default=str)
            conn.execute("""INSERT INTO orders(source_file,sheet_name,partita_col,order_json,status,created_at,updated_at)
                VALUES(?,?,?,?, 'open', ?, ?)
                ON CONFLICT(source_file,sheet_name,partita_col) DO UPDATE SET
                order_json=excluded.order_json, status='open', archived_reason=NULL,
                updated_at=excluded.updated_at, archived_at=NULL""",
                (str(source_file.resolve()), sheet_name, partita_col, payload, now, now))
            count += 1
        conn.commit()
    finally:
        conn.close()
    return count


def archive(source_file: Path, sheet_name: str, partita_cols: Iterable[Any], reason: str = "deleted", db_path: Path = DB_PATH) -> int:
    """Mark the given Partita Col rows of a sheet as archived (with a reason and time) instead of deleting them.
    Returns how many rows changed.
    """
    keys = [_key(value) for value in partita_cols if _key(value)]
    if not keys:
        return 0
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        changed = 0
        for key in keys:
            cursor = conn.execute("""UPDATE orders SET status='archived', archived_reason=?, archived_at=?, updated_at=?
                WHERE source_file=? AND sheet_name=? AND partita_col=?""",
                (reason, now, now, str(source_file.resolve()), sheet_name, key))
            changed += cursor.rowcount
        conn.commit()
        return changed
    finally:
        conn.close()


def partita_key(value: Any) -> str:
    """The normalised Partita Col key the history is stored under."""
    return _key(value)


def reconcile_sheet(source_file: Path, sheet_name: str, present_keys: set[str],
                    moved_to: dict[str, str] | None = None, db_path: Path = DB_PATH) -> int:
    """Close the open history records of *sheet_name* that are no longer in it.

    sync_rows() only adds or refreshes rows, so a row that left the sheet --
    moved PG-X -> Orders, or deleted by hand in Excel -- stayed "open" there
    (the same Partita Col then looked open in two sheets).  ``moved_to`` maps a
    key that now lives in the other sheet to that sheet's name.
    """
    moved_to = moved_to or {}
    now = datetime.now().isoformat(timespec="seconds")
    conn = _connect(db_path)
    try:
        open_keys = [
            row["partita_col"] for row in conn.execute(
                "SELECT partita_col FROM orders WHERE source_file=? AND sheet_name=? AND status='open'",
                (str(source_file.resolve()), sheet_name),
            )
        ]
        closed = 0
        for key in open_keys:
            if key in present_keys:
                continue
            reason = f"moved to {moved_to[key]}" if key in moved_to else "removed from workbook"
            conn.execute(
                """UPDATE orders SET status='archived', archived_reason=?, archived_at=?, updated_at=?
                   WHERE source_file=? AND sheet_name=? AND partita_col=? AND status='open'""",
                (reason, now, now, str(source_file.resolve()), sheet_name, key),
            )
            closed += 1
        conn.commit()
        return closed
    finally:
        conn.close()


def list_open(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM orders WHERE status='open' ORDER BY updated_at DESC")]
    finally:
        conn.close()


def list_history(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    conn = _connect(db_path)
    try:
        return [dict(row) for row in conn.execute("SELECT * FROM orders ORDER BY updated_at DESC")]
    finally:
        conn.close()


def list_shipped(db_path: Path = DB_PATH) -> list[dict[str, Any]]:
    """Every archived order whose invoice/shipment already went out (see
    delete_shipped_shared_rows's reason="shipped/invoiced") -- i.e. exactly
    what "Delete Shipped Colors" moved out of the live workbook, still kept
    here for historical extraction."""
    conn = _connect(db_path)
    try:
        return [
            dict(row) for row in conn.execute(
                "SELECT * FROM orders WHERE status='archived' AND archived_reason='shipped/invoiced' "
                "ORDER BY archived_at DESC"
            )
        ]
    finally:
        conn.close()
