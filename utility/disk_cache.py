"""Generic persistent (on-disk) cache for expensive per-file loaders.

Several parts of this app parse the same Excel source file repeatedly
within one session -- Listini, Magazino, Lotti, Densita' Query, and
Articoli.xlsx are each read from more than one tab. An in-memory cache
only helps within one running process; this also mirrors the parsed
result to disk, keyed by (path, mtime, size), so a cold app restart
against an unchanged source file skips the slow Excel parse too, not
just repeat calls in the same session.

Usage (see calculate/prezzi.py for a real example)::

    def load_something(path):
        return disk_cache.cached_load("something", path, lambda: _load_something_uncached(path))
"""
from __future__ import annotations

import copy
import hashlib
import re
import os
import pickle
from pathlib import Path
from typing import Any, Callable

from utility.utils import APP_DATA_DIR

_MEMORY_CACHE: dict[tuple, Any] = {}


def file_cache_key(path) -> tuple | None:
    """(path, mtime, size) -- None if the file can't be stat'd (missing,
    permissions), so callers can fall back to "never cache this call"."""
    try:
        stat = os.stat(path)
        return (str(path), stat.st_mtime_ns, stat.st_size)
    except OSError:
        return None


def _cache_dir() -> Path:
    directory = APP_DATA_DIR / "cache"
    directory.mkdir(parents=True, exist_ok=True)
    return directory


def _cache_path(namespace: str, cache_key: tuple) -> Path:
    # The namespace is only a readable prefix: characters such as ":" are not
    # allowed in Windows file names ("magazino:None" made the write fail, so the
    # disk cache silently never worked).  The digest covers the FULL namespace,
    # so two namespaces that sanitise to the same prefix still never collide.
    digest = hashlib.sha1(
        "|".join([str(namespace), *(str(part) for part in cache_key)]).encode("utf-8")
    ).hexdigest()
    safe_prefix = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(namespace)).strip("_.")[:40] or "cache"
    return _cache_dir() / f"{safe_prefix}_{digest}.pkl"


def _private_copy(result: Any) -> Any:
    """A caller that edits the DataFrame it got back must not be editing the
    cached one for everybody else."""
    try:
        return copy.deepcopy(result)
    except Exception:  # noqa: BLE001 -- an un-copyable result is returned as is
        return result


def cached_load(namespace: str, path, compute: Callable[[], Any],
                 is_valid: Callable[[Any], bool] = lambda result: True) -> Any:
    """Returns compute()'s result, via an in-memory cache first, then an
    on-disk one, both keyed by (path, mtime, size) -- compute() only
    actually runs when the file has genuinely changed since it was last
    cached (or was never cached at all).

    namespace keeps different loaders (different result shapes) from
    colliding in the same cache directory -- use a short, stable name
    (e.g. "prezzi", "magazino"), not the file path itself.

    is_valid(result) decides whether a result is worth caching at all --
    e.g. skip caching a failed load (so the next call retries instead of
    replaying the same failure), or an empty DataFrame. Corrupt or
    unreadable cache files are treated as a cache miss, never an error --
    caching must never be why a real load fails.
    """
    cache_key = file_cache_key(path)
    memory_key = (namespace, cache_key)
    if cache_key is not None and memory_key in _MEMORY_CACHE:
        return _private_copy(_MEMORY_CACHE[memory_key])

    disk_path = None
    if cache_key is not None:
        loaded_from_disk = False
        try:
            disk_path = _cache_path(namespace, cache_key)
            if disk_path.is_file():
                result = pickle.loads(disk_path.read_bytes())
                loaded_from_disk = True
        except Exception:  # noqa: BLE001 -- cache access failures must never block a real load
            pass
        if loaded_from_disk:
            _MEMORY_CACHE[memory_key] = result
            return _private_copy(result)

    result = compute()
    if cache_key is not None and is_valid(result):
        # Store a private copy: the caller keeps (and may modify) `result`.
        _MEMORY_CACHE[memory_key] = _private_copy(result)
        try:
            from utility.atomic import atomic_write_bytes
            atomic_write_bytes(_cache_path(namespace, cache_key), pickle.dumps(result))
        except Exception:  # noqa: BLE001 -- caching is best-effort, never blocks returning the real result
            pass
    return result


def invalidate(namespace: str | None = None) -> None:
    """Clear the in-memory cache -- all namespaces, or just one. The disk
    cache doesn't need this: a changed file gets a new (path, mtime, size)
    key automatically, so stale disk entries are simply never looked up
    again (and are harmless leftovers, not a correctness issue)."""
    if namespace is None:
        _MEMORY_CACHE.clear()
    else:
        for key in [k for k in _MEMORY_CACHE if k[0] == namespace]:
            del _MEMORY_CACHE[key]
