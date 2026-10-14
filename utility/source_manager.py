"""SQLite-first source manager with content-aware in-process memoization.

Excel workbooks are update/import inputs only. This module centralizes snapshot
reads, freshness checks, and a defensive RAM cache so several pages can reuse a
normalized frame without repeatedly decoding the same SQLite JSON payload.
"""
from __future__ import annotations

import importlib
import os
from pathlib import Path
from typing import Any

import pandas as pd

from utility import situazione_db as db

# Snapshot name -> metadata cache updated by the corresponding upload controls.
# These small files remember the selected source path; they are not the data store.
_PATH_CACHES = {
    "magazino_summary": ("utility.magazino_cache", "load_magazino_cache"),
    "lotti_summary": ("utility.lotti_cache", "load_lotti_cache"),
    "lotti_data": ("utility.lotti_cache", "load_lotti_cache"),
    "listini": ("utility.prezzi_cache", "load_prezzi_cache"),
    "densita_lookup": ("utility.densita_cache", "load_densita_cache"),
    "articoli_marca": ("utility.articoli_cache", "load_articoli_cache"),
}

# source -> (content fingerprint, normalized frame). Always return a copy so one
# page cannot accidentally mutate the shared copy observed by another page.
_MEMORY: dict[str, tuple[str, pd.DataFrame]] = {}


def _registered_path(name: str) -> str:
    entry = _PATH_CACHES.get(str(name))
    if not entry:
        return ""
    try:
        module = importlib.import_module(entry[0])
        return str(getattr(module, entry[1])().get("source_path", "") or "")
    except Exception:
        return ""


def is_current(name: str) -> bool:
    """Whether the snapshot matches the currently registered source file.

    A missing/deleted workbook is fine after import because SQLite is canonical.
    If another page registers a newer file or the same path was overwritten,
    callers get a cache miss and import that file before using the data.
    """
    registered = _registered_path(name)
    if not registered or not os.path.isfile(registered):
        return True
    try:
        meta = db.snapshot_meta(name)
    except Exception:
        return True
    if not meta or not meta.get("source_path"):
        # For an old snapshot without origin metadata, prefer it over making an
        # unsolicited Excel dependency. The next explicit upload records origin.
        return True
    same_path = os.path.normcase(os.path.normpath(str(meta["source_path"]))) == \
        os.path.normcase(os.path.normpath(registered))
    try:
        same_time = int(meta.get("source_mtime_ns") or 0) == os.stat(registered).st_mtime_ns
    except OSError:
        return True
    return same_path and same_time


def invalidate(name: str | None = None) -> None:
    """Drop one memoized source or all sources after explicit invalidation."""
    if name is None:
        _MEMORY.clear()
    else:
        _MEMORY.pop(str(name), None)


def load(name: str) -> pd.DataFrame | None:
    """Return a defensive copy from RAM or SQLite, or None if no/current snapshot."""
    key = str(name)
    try:
        if not is_current(key):
            invalidate(key)
            return None
        fingerprint = db.snapshot_fingerprint(key)
        cached = _MEMORY.get(key)
        if fingerprint and cached and cached[0] == fingerprint:
            return cached[1].copy(deep=True)
        frame = db.load_frame_cache(key)
        if frame is None:
            invalidate(key)
            return None
        # Reading a legacy frame may migrate it to compact payload storage; the
        # content fingerprint is unchanged, so the initial value is still valid.
        current_fingerprint = db.snapshot_fingerprint(key) or fingerprint
        if not current_fingerprint:
            # One-time migration for the oldest installations that still have
            # only frame_cache.data_json and no source_snapshot fingerprint.
            # Carry over the registered path as metadata, if available; it is
            # never needed to restore the data after this migration.
            registered = _registered_path(key)
            try:
                db.save_frame_cache(key, frame, source_path=registered or None)
                current_fingerprint = db.snapshot_fingerprint(key)
            except Exception:
                current_fingerprint = ""
        if not current_fingerprint:
            current_fingerprint = db.frame_fingerprint(frame)
        _MEMORY[key] = (current_fingerprint, frame.copy(deep=True))
        return frame.copy(deep=True)
    except Exception:
        invalidate(key)
        return None


def save(name: str, frame: pd.DataFrame, source_path: str | Path | None = None) -> bool:
    """Persist a normalized source and update RAM immediately; True means changed."""
    if frame is None:
        return False
    key = str(name)
    changed = bool(db.save_frame_cache(key, frame, source_path=source_path))
    try:
        fingerprint = db.snapshot_fingerprint(key)
        if fingerprint:
            _MEMORY[key] = (fingerprint, frame.copy(deep=True))
        else:
            invalidate(key)
    except Exception:
        invalidate(key)
    return changed


def metadata(name: str) -> dict[str, Any]:
    """Return upload metadata without requiring the original workbook to exist."""
    try:
        return db.get_upload(name) or {}
    except Exception:
        return {}


def source_name(name: str) -> str:
    return str(metadata(name).get("file_name", ""))
