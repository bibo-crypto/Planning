"""Excel I/O helpers: crash-safe saving and user-facing file-lock errors."""
from __future__ import annotations

import os
import shutil
import tempfile
import zipfile
from pathlib import Path


def _looks_like_valid_xlsx(path: Path) -> bool:
    """Cheap integrity check of a just-written workbook: a readable ZIP whose
    parts all pass their CRC and that holds the two parts every workbook has."""
    try:
        with zipfile.ZipFile(path) as archive:
            names = set(archive.namelist())
            return (
                "[Content_Types].xml" in names
                and "xl/workbook.xml" in names
                and archive.testzip() is None
            )
    except (zipfile.BadZipFile, OSError):
        return False


def _lock_error(path: Path, exc: OSError) -> RuntimeError | None:
    message = str(exc).lower()
    if isinstance(exc, PermissionError):
        return RuntimeError(
            f"Cannot save '{path.name}'. The Excel file is open or locked. "
            "Close it in Excel (including any hidden Excel window) and try again."
        )
    if "permission" in message or "being used" in message or "locked" in message:
        return RuntimeError(
            f"Cannot save '{path.name}' because it is open or locked. "
            "Close the Excel file and try again."
        )
    return None


def safe_save_workbook(workbook, path: Path, keep_backup: bool = True) -> None:
    """Save an openpyxl workbook without ever leaving a half-written file.

    The workbook is written to a temporary file in the same folder and checked;
    only then does it replace the original (atomic rename).  A failure at any
    point -- full disk, crash, locked file -- leaves the original exactly as it
    was.  Before the swap the previous version is kept as ``<name>.previous.xlsx`` so the
    last good file can be restored by hand.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.stem}.", suffix=path.suffix + ".tmp", dir=path.parent)
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        workbook.save(temp_path)
        if not _looks_like_valid_xlsx(temp_path):
            raise RuntimeError(
                f"Saving '{path.name}' produced an invalid workbook; the original file was left unchanged."
            )
        if keep_backup and path.is_file():
            try:
                shutil.copy2(path, path.with_name(f"{path.stem}.previous{path.suffix}"))
            except OSError:
                pass  # a missing backup must never block the save itself
        os.replace(temp_path, path)
    except OSError as exc:
        translated = _lock_error(path, exc)
        if translated is not None:
            raise translated from exc
        raise
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass
