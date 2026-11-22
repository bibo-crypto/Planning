"""Shared helper for tests that need a real ``tk.Tk()`` root window.

On a developer's Windows PC ``tk.Tk()`` sometimes fails once with "Can't find a usable init.tcl / tk.tcl" while
hundreds of other Tk tests pass in the same run.  The old fixtures turned *any* ``TclError`` into ``pytest.skip``,
which silently hid that (the tests showed up as "skipped", not as a problem).  ``create_tk_root`` retries a few
times and only skips when there is genuinely no display (Linux without a usable X display); everywhere else the
real error is raised once the retries are used up.
"""
import os
import sys
import time
import tkinter as tk

import pytest

ATTEMPTS = 5
DELAY_SECONDS = 0.5


def _display_is_missing(exc: Exception) -> bool:
    """True when *exc* means "there is no display to open a window on" (only possible on Linux / X11)."""
    if not sys.platform.startswith("linux"):
        return False        # Windows and macOS always have a display: a TclError there is a real problem
    if not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        return True
    message = str(exc).lower()
    return "no display name" in message or "couldn't connect to display" in message


def create_tk_root(attempts: int = ATTEMPTS, delay: float = DELAY_SECONDS) -> tk.Tk:
    """Return a new ``tk.Tk()``; retry transient failures, skip only without a display, otherwise raise the real error."""
    last_error: tk.TclError | None = None
    for attempt in range(1, attempts + 1):
        try:
            return tk.Tk()
        except tk.TclError as exc:
            if _display_is_missing(exc):
                pytest.skip(f"no display available for Tk: {exc}")
            last_error = exc
            if attempt < attempts:
                time.sleep(delay)
    assert last_error is not None
    raise last_error
