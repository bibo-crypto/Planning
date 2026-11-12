"""The real application start: every page is built, and a page that fails to build is reported.

Regression for the release that stayed on "Loading application pages..." for ever: a TypeError inside
``_build_ui`` (a keyword the page builder did not accept) only reached Tk's callback handler, so a
windowed EXE showed nothing.  These tests start the real ``ConverterApp`` (isolated data folder from
``conftest.py``) and pump its event loop exactly like ``mainloop`` does.
"""
import time
import tkinter as tk
import traceback
from tkinter import messagebox, ttk

import pytest

from gui import gui as gui_module
from gui.gui import ConverterApp

REQUIRED_PAGES = (
    "_timeline_tab", "_show_orders_tab", "_biglietti_tab", "_kamal_tab",
    "_ordine_med_tab", "_settimana_tab", "_master_data_tab",
)


@pytest.fixture()
def start_app(monkeypatch):
    """Create the app, collect Tk callback errors, and run it until the loading label is gone or *timeout*."""
    apps = []
    errors = []
    shown = []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: shown.append(a))
    monkeypatch.setattr(gui_module.ConverterApp, "_check_for_updates", lambda self: None)

    def start(timeout=60):
        try:
            app = ConverterApp()
        except tk.TclError:
            pytest.skip("no display")
        apps.append(app)
        app.report_callback_exception = lambda t, v, tb: errors.append((t, v, "".join(traceback.format_exception(t, v, tb))))
        end = time.time() + timeout
        while time.time() < end:
            app.update()
            label = getattr(app, "_startup_label", None)
            if errors or label is None or not label.winfo_exists():
                break
            time.sleep(0.02)
        return app, errors, shown

    yield start
    for app in apps:
        try:
            app.destroy()
        except tk.TclError:
            pass


def _visit_every_tab(app, visited=None):
    """Select every tab of every notebook, nested ones included (pages are built lazily when first shown)."""
    visited = set() if visited is None else visited
    stack = [app]
    while stack:
        parent = stack.pop()
        for child in parent.winfo_children():
            if isinstance(child, ttk.Notebook) and str(child) not in visited:
                visited.add(str(child))
                for tab_id in child.tabs():
                    child.select(tab_id)
                    app.update()
                    stack.append(app.nametowidget(tab_id))
            else:
                stack.append(child)


def test_startup_builds_every_page_and_leaves_the_loading_screen(start_app):
    app, errors, shown = start_app()
    assert errors == [], errors[0][2] if errors else ""
    assert shown == []
    assert not app._startup_label.winfo_exists(), "still on the loading screen"
    errors_before_visit = len(errors)
    _visit_every_tab(app)
    assert errors[errors_before_visit:] == [], errors[-1][2] if errors else ""
    missing = [name for name in REQUIRED_PAGES if getattr(app, name, None) is None]
    assert missing == []


def test_a_page_that_fails_to_build_is_logged_shown_and_not_swallowed(start_app, monkeypatch, caplog):
    def broken_build_ui(self):
        raise TypeError("_source_bar() got an unexpected keyword argument 'button_min_width'")

    monkeypatch.setattr(gui_module.ConverterApp, "_build_ui", broken_build_ui)
    with caplog.at_level("ERROR", logger="converter"):
        app, errors, shown = start_app(timeout=10)
    # not swallowed: the original exception still reaches Tk's callback handler
    assert len(errors) == 1 and errors[0][0] is TypeError
    # shown: the user gets a message naming the error and the log file instead of a silent loading label
    assert len(shown) == 1 and "button_min_width" in shown[0][1] and "converter.log" in shown[0][1]
    label_text = app._startup_label.cget("text")
    assert "could not load its pages" in label_text and "button_min_width" in label_text
    # logged with the traceback
    assert any(r.exc_info and r.exc_info[0] is TypeError for r in caplog.records)
