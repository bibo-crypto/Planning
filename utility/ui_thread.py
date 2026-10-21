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


def post_to_ui(widget: tk.Misc, callback: Callable[..., Any], *args: Any) -> bool:
    """Run ``callback(*args)`` on the UI thread as soon as possible.

    ``widget`` is any live Tk widget (it only supplies the event loop).
    Returns True when the callback was scheduled, False when the UI is already
    gone -- in that case there is nobody left to show the result to, so the
    callback is dropped (logged at debug level) rather than raised.
    """
    try:
        widget.after(0, callback, *args)
        return True
    except (tk.TclError, RuntimeError) as exc:
        logger.debug("UI is gone; dropped %s: %s", getattr(callback, "__name__", callback), exc)
        return False
