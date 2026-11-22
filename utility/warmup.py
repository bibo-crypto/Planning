"""Import the heavy libraries on background threads while the main window is being built.

The log of a real installation shows 4-11 s (average 7.5 s) between "Planning vX starting" and "all pages built". Nearly all of
it is the main thread importing pandas/numpy and openpyxl/lxml/Pillow, one after the other, while the window waits. Importing
is mostly reading and loading many small files (on Windows each one is also scanned by the antivirus), which leaves the CPU
free, so doing it on background threads at the same time as the rest of the start-up shortens the wait.

This changes WHEN the modules are imported, never what is imported or how: the main thread still runs ``import pandas`` where
the code always did, and simply finds it done (or waits for the thread that is doing it -- Python's import lock makes that safe).
Any problem here is swallowed: the normal import then happens (and reports its error) exactly as before.
"""
from __future__ import annotations

import importlib
import os
import threading

from utility.utils import logger

# Each tuple is imported in order on ITS OWN thread; the two chains do not depend on each other.
IMPORT_CHAINS: tuple[tuple[str, ...], ...] = (
    ("numpy", "pandas"),
    ("lxml.etree", "openpyxl"),
)

_started: list[threading.Thread] = []
_lock = threading.Lock()


def _import_chain(modules: tuple[str, ...]) -> None:
    for name in modules:
        try:
            importlib.import_module(name)
        except Exception:                      # noqa: BLE001 -- the real import will raise (and log) it where it is needed
            logger.debug("Import warm-up: %s could not be imported", name, exc_info=True)
            return


def start_import_warmup(chains: tuple[tuple[str, ...], ...] = IMPORT_CHAINS) -> list[threading.Thread]:
    """Start the background imports once; returns the threads (empty when disabled or already started).

    Set the environment variable ``PLANNING_NO_WARMUP=1`` to switch it off.
    """
    if os.environ.get("PLANNING_NO_WARMUP"):
        return []
    with _lock:
        if _started:
            return []
        for index, chain in enumerate(chains):
            thread = threading.Thread(target=_import_chain, args=(chain,), name=f"import-warmup-{index}", daemon=True)
            _started.append(thread)
            thread.start()
        return list(_started)
