"""Crash-safe file writes: write beside the target, then swap it in.

A plain ``path.write_text()`` truncates the file first, so a crash, a full
disk or a power cut half-way through leaves a broken file.  Here the data goes
to a temporary file in the SAME folder (so the final rename stays on one
volume and is atomic) and ``os.replace`` swaps it in only when the write
finished.  The old file is untouched until that moment.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_bytes(path: Path | str, data: bytes) -> None:
    """Write a file atomically: the bytes go to a temporary file in the same folder, are flushed to disk, and then replace the target in one step; the temporary file is removed on any error."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except BaseException:
        try:
            os.unlink(temp_name)
        except OSError:
            pass
        raise


def atomic_write_text(path: Path | str, text: str, encoding: str = "utf-8") -> None:
    atomic_write_bytes(path, text.encode(encoding))
