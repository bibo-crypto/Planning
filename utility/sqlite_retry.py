"""Small retry helpers for transient SQLite open and PRAGMA failures."""
from __future__ import annotations

import sqlite3
import time
from collections.abc import Callable, Iterable
from typing import Any

from utility.utils import logger

TRANSIENT_MESSAGES = ("database is locked", "disk i/o error")


def is_transient_sqlite_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    return isinstance(exc, sqlite3.OperationalError) and any(marker in text for marker in TRANSIENT_MESSAGES)


def run_with_sqlite_retry(operation: Callable[[], Any], attempts: int = 4, base_delay: float = 0.2) -> Any:
    """Run an SQLite operation, retrying only known transient operational errors."""
    last_error: BaseException | None = None
    for attempt in range(1, attempts + 1):
        try:
            return operation()
        except sqlite3.OperationalError as exc:
            last_error = exc
            if not is_transient_sqlite_error(exc) or attempt == attempts:
                raise
            logger.warning(
                "SQLite attempt %d/%d failed (%s); retrying",
                attempt,
                attempts,
                exc,
            )
            time.sleep(base_delay * attempt)
    assert last_error is not None
    raise last_error


def connect_with_retry(
    path: Any,
    *,
    timeout: float = 10,
    pragmas: Iterable[str] = (),
    row_factory: sqlite3.Row | None = None,
    attempts: int = 4,
    base_delay: float = 0.2,
) -> sqlite3.Connection:
    """Open a connection and execute PRAGMAs as one retried operation."""
    def open_once() -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=timeout)
        try:
            if row_factory is not None:
                connection.row_factory = row_factory
            for pragma in pragmas:
                connection.execute(pragma)
            return connection
        except BaseException:
            connection.close()
            raise

    return run_with_sqlite_retry(open_once, attempts=attempts, base_delay=base_delay)
