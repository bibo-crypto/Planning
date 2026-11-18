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

import tkinter as tk
from typing import Any, Callable

from utility.utils import logger


def post_to_ui(widget: tk.Misc, callback: Callable[..., Any], *args: Any, on_dropped: Callable[[], Any] | None = None) -> bool:
    """Run ``callback(*args)`` on the UI thread as soon as possible.

    ``widget`` is any live Tk widget (it only supplies the event loop).
    Returns True when the callback was scheduled, False when the UI is already
    gone -- in that case there is nobody left to show the result to, so the
    callback is dropped (logged at debug level) rather than raised.

    The callback is also dropped while the main thread is not in mainloop (for example inside a modal dialog:
    "main thread is not in main loop").  A worker that marked an operation as "running" releases that flag in its
    callback, so a dropped callback would leave the operation blocked for ever: pass ``on_dropped`` (it runs on the
    calling thread, only when nothing was scheduled) to release it.
    """
    try:
        widget.after(0, callback, *args)
        return True
    except (tk.TclError, RuntimeError) as exc:
        logger.debug("UI is gone; dropped %s: %s", getattr(callback, "__name__", callback), exc)
        if on_dropped is not None:
            try:
                on_dropped()
            except Exception:  # noqa: BLE001 -- must not turn a dropped result into a crashing worker
                logger.warning("on_dropped of %s failed", getattr(callback, "__name__", callback), exc_info=True)
        return False
