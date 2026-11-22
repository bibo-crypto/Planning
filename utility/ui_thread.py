"""Hand work from a background thread to the Tk main loop, safely.

Tkinter widgets may only be touched from the main thread, so every worker thread
in the app finishes by scheduling a callback with ``widget.after(0, ...)``.
That call itself can fail while the app is closing (the widget -- or the whole
interpreter -- is already gone): the worker then dies with an unhandled
``TclError``/``RuntimeError`` traceback.  ``post_to_ui`` is the one place that
knows about this, so the ~35 hand-off sites stay one-liners and a window closed
mid-task ends quietly instead of printing a stack trace.
"""
from __future__ import annotations

import time
import tkinter as tk
from typing import Any, Callable

from utility.utils import logger

RETRY_INTERVAL_SECONDS = 0.05      # how often post_to_ui(retry_for=...) tries again while the main thread is not in mainloop


def post_to_ui(widget: tk.Misc, callback: Callable[..., Any], *args: Any,
               on_dropped: Callable[[], Any] | None = None, retry_for: float = 0.0) -> bool:
    """Run ``callback(*args)`` on the UI thread as soon as possible.

    ``widget`` is any live Tk widget (it only supplies the event loop).
    Returns True when the callback was scheduled, False when the UI is already
    gone -- in that case there is nobody left to show the result to, so the
    callback is dropped (logged at debug level) rather than raised.

    The callback is also dropped while the main thread is not in mainloop (for example inside a modal dialog:
    "main thread is not in main loop").  A worker that marked an operation as "running" releases that flag in its
    callback, so a dropped callback would leave the operation blocked for ever: pass ``on_dropped`` (it runs on the
    calling thread, only when nothing was scheduled) to release it.

    ``retry_for`` (seconds, default 0 = the behaviour above) is for a worker whose result matters even if a modal
    dialog is open for a while: while the main thread is "not in main loop" the call is repeated from the calling
    thread every ``RETRY_INTERVAL_SECONDS`` until it works or *retry_for* seconds have passed (only then is the
    callback dropped).  It blocks the CALLING thread, so use it from a worker thread only.  A destroyed UI
    (``TclError``) is final and is never retried.
    """
    deadline = time.monotonic() + retry_for
    while True:
        try:
            widget.after(0, callback, *args)
            return True
        except RuntimeError as exc:
            if time.monotonic() < deadline:
                time.sleep(RETRY_INTERVAL_SECONDS)
                continue
            error = exc
        except tk.TclError as exc:
            error = exc
        break
    logger.debug("UI is gone; dropped %s: %s", getattr(callback, "__name__", callback), error)
    if on_dropped is not None:
        try:
            on_dropped()
        except Exception:  # noqa: BLE001 -- must not turn a dropped result into a crashing worker
            logger.warning("on_dropped of %s failed", getattr(callback, "__name__", callback), exc_info=True)
    return False
