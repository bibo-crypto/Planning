"""Portable backup/restore for Planning application state."""
from __future__ import annotations

from datetime import date, datetime
from pathlib import Path
import re
import shutil
import sqlite3
import tempfile
import zipfile

from utility.utils import APP_DATA_DIR, logger

BACKUP_PREFIX = "planning_backup"
KEEP_DAYS = 10
BACKUP_DIR = APP_DATA_DIR / "backups"
_STAMP = re.compile(rf"^{BACKUP_PREFIX}_(\d{{8}})_\d{{6}}\.zip$")


def _backup_day(path: Path) -> date:
    """The day a backup was made: from its name (planning_backup_YYYYMMDD_HHMMSS.zip), else its file time."""
    match = _STAMP.match(path.name)
    if match:
        try:
            return datetime.strptime(match.group(1), "%Y%m%d").date()
        except ValueError:
            pass
    return datetime.fromtimestamp(path.stat().st_mtime).date()


def _prune_old_backups(directory: Path) -> None:
    """Keep only the backups of the ten most recent DAYS (every backup of those days stays).

    Only this application's timestamped archives are considered, so a user
    can safely save a backup in a folder that also contains other ZIP files.
    """
    try:
        backups = [path for path in directory.glob(f"{BACKUP_PREFIX}_*.zip") if path.is_file()]
        keep = set(sorted({_backup_day(path) for path in backups}, reverse=True)[:KEEP_DAYS])
        for path in backups:
            if _backup_day(path) not in keep:
                path.unlink()
    except OSError:
        # A backup must never fail merely because an older archive is open or
        # protected by another process.  It will be pruned on a later run.
        pass


def daily_backup(directory: Path | None = None, today: date | None = None) -> Path | None:
    """Make today's automatic backup unless one was already made today; None when nothing was done.

    Never raises: the program must start even when the backup cannot be written."""
    directory = Path(directory) if directory else BACKUP_DIR
    today = today or date.today()
    try:
        if any(_backup_day(path) == today for path in directory.glob(f"{BACKUP_PREFIX}_*.zip")):
            return None
        return create_backup(directory / f"{BACKUP_PREFIX}_{datetime.combine(today, datetime.now().time()):%Y%m%d_%H%M%S}.zip")
    except Exception:  # noqa: BLE001 -- the program must start; the failure is recorded, not hidden
        logger.warning("Automatic daily backup failed", exc_info=True)
        return None


# Never part of a backup, at any depth.  When the app runs from source,
# APP_DATA_DIR is the project folder, which also holds the virtualenv, the git
# history and build output -- none of that is application data.
_SKIP_TOP_LEVEL = {"backups", "logs"}
_SKIP_ANYWHERE = {"venv", ".venv", "env", ".git", "__pycache__", "node_modules", "dist", "build", ".pytest_cache"}
_SQLITE_SUFFIXES = {".sqlite", ".sqlite3", ".db"}
_SQLITE_SIDECARS = ("-wal", "-shm", "-journal")


def _is_sqlite_sidecar(path: Path) -> bool:
    return any(path.name.endswith(suffix) for suffix in _SQLITE_SIDECARS)


def _snapshot_sqlite(source: Path, target: Path) -> bool:
    """Consistent copy of a live SQLite database via SQLite's own backup API
    (zipping the raw file while it is being written can capture a torn state,
    and the -wal file must match it).  False if *source* isn't a readable
    database, in which case the caller falls back to the plain file."""
    try:
        reader = sqlite3.connect(f"file:{source.as_posix()}?mode=ro", uri=True, timeout=10)
        try:
            writer = sqlite3.connect(target)
            try:
                reader.backup(writer)
            finally:
                writer.close()
        finally:
            reader.close()
        return True
    except sqlite3.Error as exc:
        # The caller falls back to zipping the plain file (not a consistent snapshot) -- say so in the log.
        logger.warning("Could not take a consistent SQLite snapshot of %s (%s); the plain file is backed up instead",
                       source.name, exc)
        return False


def create_backup(destination: str | Path) -> Path:
    """Zip application data, SQLite databases, settings and caches."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="planning-backup-") as scratch, \
            zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        if APP_DATA_DIR.exists():
            for path in APP_DATA_DIR.rglob("*"):
                if not path.is_file() or _is_sqlite_sidecar(path):
                    continue
                relative = path.relative_to(APP_DATA_DIR)
                if relative.parts and relative.parts[0] in _SKIP_TOP_LEVEL:
                    continue
                if any(part in _SKIP_ANYWHERE for part in relative.parts[:-1]):
                    continue
                if destination.resolve() == path.resolve():
                    continue
                source = path
                if path.suffix.lower() in _SQLITE_SUFFIXES:
                    copy = Path(scratch) / f"{abs(hash(str(relative)))}.db"
                    if _snapshot_sqlite(path, copy):
                        source = copy
                archive.write(source, arcname=str(relative))
        archive.writestr("backup_info.txt", f"Created: {datetime.now().isoformat()}\n")
    _prune_old_backups(destination.parent)
    return destination


def restore_backup(source: str | Path) -> int:
    """Safely restore a backup into APP_DATA_DIR; return restored file count."""
    source = Path(source)
    if not source.is_file() or not zipfile.is_zipfile(source):
        raise ValueError("The selected file is not a valid Planning backup.")
    APP_DATA_DIR.mkdir(parents=True, exist_ok=True)
    restored = 0
    with tempfile.TemporaryDirectory(prefix="planning-restore-") as temp:
        temp_root = Path(temp)
        with zipfile.ZipFile(source) as archive:
            for member in archive.infolist():
                name = Path(member.filename)
                if name.is_absolute() or ".." in name.parts or name.name == "backup_info.txt":
                    continue
                archive.extract(member, temp_root)
        for path in temp_root.rglob("*"):
            if not path.is_file():
                continue
            target = APP_DATA_DIR / path.relative_to(temp_root)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.suffix.lower() in _SQLITE_SUFFIXES:
                # A leftover -wal/-shm from the database being replaced would be
                # replayed onto the restored file and corrupt it.
                for suffix in _SQLITE_SIDECARS:
                    sidecar = target.with_name(target.name + suffix)
                    try:
                        sidecar.unlink()
                    except FileNotFoundError:
                        pass
            shutil.copy2(path, target)
            restored += 1
    return restored
