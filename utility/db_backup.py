"""Daily backup of the program's SQLite databases, and restoring one of them.

Single responsibility: copy the databases into ``<app data>/backups`` once a day, keep
only the newest KEEP_DAYS days, and put a chosen backup back.  Nothing here touches Tk;
gui/backup_menu.py shows the menu entries.

Files: ``<database>_<YYYY-MM-DD>.<ext>`` (e.g. ``dyeing_tracker_2026-11-02.db``).  The copy
goes through SQLite's own backup API, so it is consistent even while the program is
writing (WAL mode included).  The installer and the build already leave ``backups`` out
of the release, so a backup never travels to another machine by accident.
"""
from __future__ import annotations

import os
import re
import sqlite3
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path

from utility.utils import APP_DATA_DIR, logger

KEEP_DAYS = 10
KEEP_SAFETY_COPIES = 3          # the "before restore" copies made when a backup is put back
BACKUP_DIR: Path = APP_DATA_DIR / "backups"

_DATED = re.compile(r"^(?P<name>.+)_(?P<day>\d{4}-\d{2}-\d{2})\.(?P<ext>db|sqlite3)$")


@dataclass(frozen=True)
class Database:
    """One database of the program: its backup name and where it lives now."""
    name: str
    path: Path

    @property
    def ext(self) -> str:
        return self.path.suffix.lstrip(".") or "db"


def databases() -> list[Database]:
    """The databases to protect (paths are read at call time, so tests can redirect them)."""
    from utility import orders_db, situazione_db
    return [
        Database("dyeing_tracker", Path(situazione_db.DB_PATH)),
        Database("planning_orders", Path(orders_db.DB_PATH)),
    ]


def _copy(source: Path, destination: Path) -> None:
    """Copy one SQLite file with the backup API, replacing ``destination`` only when complete."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(destination.name + ".part")
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=10)
    try:
        dst = sqlite3.connect(temporary)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    os.replace(temporary, destination)


def backup_path(db: Database, day: date) -> Path:
    return BACKUP_DIR / f"{db.name}_{day.isoformat()}.{db.ext}"


def create_backup(force: bool = False, today: date | None = None) -> list[Path]:
    """Back up every database that exists, once per day (``force`` overwrites today's copy).

    Returns the files written.  Old days beyond KEEP_DAYS are removed afterwards."""
    today = today or date.today()
    written: list[Path] = []
    for db in databases():
        target = backup_path(db, today)
        if not db.path.is_file() or (target.exists() and not force):
            continue
        try:
            _copy(db.path, target)
            written.append(target)
        except Exception as exc:  # noqa: BLE001 -- a failed backup must never stop the program
            logger.warning("Backup of %s failed: %s", db.name, exc)
    prune()
    if written:
        logger.info("Database backup: %s", ", ".join(p.name for p in written))
    return written


def list_backups() -> list[tuple[str, date, Path]]:
    """(database name, day, file) of every daily backup, newest first."""
    found = []
    if BACKUP_DIR.is_dir():
        for path in BACKUP_DIR.iterdir():
            match = _DATED.match(path.name)
            if match:
                found.append((match["name"], date.fromisoformat(match["day"]), path))
    return sorted(found, key=lambda item: (item[1], item[0]), reverse=True)


def prune(keep_days: int = KEEP_DAYS) -> list[Path]:
    """Delete the backups of every database except its newest ``keep_days`` days."""
    removed: list[Path] = []
    by_name: dict[str, list[tuple[date, Path]]] = {}
    for name, day, path in list_backups():
        by_name.setdefault(name, []).append((day, path))
    for entries in by_name.values():
        for _day, path in sorted(entries, reverse=True)[keep_days:]:
            try:
                path.unlink()
                removed.append(path)
            except OSError as exc:
                logger.warning("Could not delete the old backup %s: %s", path.name, exc)
    # The safety copies made before a restore: keep the latest few only.
    safety = sorted(BACKUP_DIR.glob("*_before_restore_*"), key=lambda p: p.stat().st_mtime, reverse=True) if BACKUP_DIR.is_dir() else []
    for path in safety[KEEP_SAFETY_COPIES:]:
        try:
            path.unlink()
            removed.append(path)
        except OSError:
            pass
    return removed


def database_for_backup(path: Path) -> Database | None:
    """Which database a backup file belongs to (from its name), or None when it is not one of ours."""
    match = _DATED.match(Path(path).name)
    if not match:
        return None
    return next((db for db in databases() if db.name == match["name"]), None)


def verify(path: Path) -> None:
    """Raise ValueError unless ``path`` is a healthy SQLite database."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            result = conn.execute("PRAGMA integrity_check").fetchone()
        finally:
            conn.close()
    except sqlite3.Error as exc:
        raise ValueError(f"Not a readable database: {exc}") from exc
    if not result or result[0] != "ok":
        raise ValueError("The backup file is damaged (integrity check failed).")


def restore_backup(path: Path) -> Path:
    """Put the backup ``path`` back as the live database.

    The current database is first copied to ``<name>_before_restore_<time>`` in the backups
    folder, so a wrong choice can be undone.  Returns that safety copy.  The program must be
    restarted afterwards (its pages keep what they already loaded)."""
    path = Path(path)
    db = database_for_backup(path)
    if db is None:
        raise ValueError("This file is not one of the program's backups (name_YYYY-MM-DD.db / .sqlite3).")
    verify(path)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    safety = BACKUP_DIR / f"{db.name}_before_restore_{stamp}.{db.ext}"
    if db.path.is_file():
        _copy(db.path, safety)
    db.path.parent.mkdir(parents=True, exist_ok=True)
    src = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        dst = sqlite3.connect(db.path, timeout=10)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    prune()
    logger.info("Database %s restored from %s", db.name, path.name)
    return safety
