"""A worker's result that cannot reach the UI must not leave its operation blocked.

Every background operation of the shared-orders pages (PG-X save, PG-X editor save, move/delete rows, delete shipped colours,
Partita GG upload) marks itself as running and clears the mark in the callback that runs on the UI thread.  When tkinter
refuses to schedule that callback ("main thread is not in main loop", e.g. while a modal dialog is open) the callback is
dropped, the mark stayed set, and every later click on that button silently did nothing until the program restarted.
These tests drop the first result on purpose and check that the operation can be started again and then completes.
"""
import time
import tkinter as tk
from tkinter import messagebox

import pandas as pd
import pytest

from exporters.biglietti import shared_workbook as sw
from tests.test_shared_workbook_scenarios import keys, rec, row_of
from tests.test_upload_gg_scenarios import Calls, UploadHost, pump_until, root, shared  # noqa: F401  (fixtures)
from utility.ui_thread import post_to_ui


# ------------------------------------------------------------------ post_to_ui itself
def test_post_to_ui_schedules_and_does_not_call_on_dropped(root):
    ran, dropped = [], []
    assert post_to_ui(root, lambda: ran.append(1), on_dropped=lambda: dropped.append(1)) is True
    root.update()
    assert ran == [1] and dropped == []


def test_post_to_ui_passes_positional_arguments_as_before(root):
    seen = []
    assert post_to_ui(root, lambda a, b: seen.append((a, b)), 1, "x") is True
    root.update()
    assert seen == [(1, "x")]


@pytest.mark.parametrize("error", [tk.TclError("application has been destroyed"), RuntimeError("main thread is not in main loop")])
def test_post_to_ui_runs_on_dropped_when_nothing_could_be_scheduled(error):
    class Gone:
        def after(self, *_a):
            raise error

    dropped = []
    assert post_to_ui(Gone(), lambda: None, on_dropped=lambda: dropped.append(1)) is False
    assert dropped == [1]
    assert post_to_ui(Gone(), lambda: None) is False                                  # without on_dropped: still just False


def test_a_failing_on_dropped_is_logged_and_never_raised(caplog):
    class Gone:
        def after(self, *_a):
            raise RuntimeError("main thread is not in main loop")

    def broken():
        raise ValueError("boom")

    with caplog.at_level("WARNING", logger="converter"):
        assert post_to_ui(Gone(), lambda: None, on_dropped=broken) is False
    assert any("on_dropped" in r.getMessage() and r.exc_info for r in caplog.records)


# ------------------------------------------------------------------ the operations
def stall(root, seconds=3.5):
    """The main thread is busy outside mainloop (inside a modal dialog): workers cannot post anything."""
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.02)


class Quiet:
    def __init__(self, monkeypatch):
        self.infos, self.errors, self.asked = [], [], []
        monkeypatch.setattr(messagebox, "showinfo", lambda title, text, **kw: self.infos.append((title, text)))
        monkeypatch.setattr(messagebox, "showerror", lambda title, text, **kw: self.errors.append((title, text)))
        monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: (self.asked.append((title, text)), True)[1])


KEEP = []          # Tk variables must be released on the main thread, not by a worker dropping the last reference

STOCK = pd.DataFrame([{"articolo": "G101", "partita": "159001", "mag_rocche": 40.0, "mag_peso": 80.0, "lotto": ""}])


def test_a_pgx_partita_save_is_not_ignored_after_its_result_was_dropped(root, monkeypatch, shared):
    """The first run wrote the assignment (only its message was lost); the repeated click must answer, not do nothing."""
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    calls = Calls()
    KEEP.append(calls)
    args = (root, "5", "159001", {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild, calls.var)
    host._save_pg_x_in_background(*args)
    stall(root)
    assert host._pg_x_saving is False
    assert "5" in keys(shared, "Orders") and "5" not in keys(shared, "PG-X")           # the first run did save
    host._save_pg_x_in_background(*args)                                              # the same click again is NOT ignored ...
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors == [("PG-X Save Error", "Partita Col '5' was not found in PG-X.")]       # ... it says what happened


def test_a_pgx_partita_save_works_normally_when_the_result_is_delivered(root, monkeypatch, shared):
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    calls = Calls()
    KEEP.append(calls)
    host._save_pg_x_in_background(root, "5", "159001", {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild, calls.var)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors == [] and dialogs.infos[-1][0] == "PG-X Saved" and "Available raw yarn: 40 rocche" in dialogs.infos[-1][1]
    assert host._pg_x_saving is False and calls.rebuilt == [True] and calls.var.get() == ""


def test_the_pgx_editor_save_can_be_repeated_after_its_result_was_dropped(root, monkeypatch, shared):
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    calls = Calls()
    KEEP.append(calls)
    values = {"Articolo": "C101", "Titolo": "30/1", "Print": "", "Partita GG": "", "Bagno": "B9", "Rocche": "10", "M/C": "7"}
    args = (root, "5", values, {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild, calls.var)
    host._save_pg_x_details_in_background(*args)
    stall(root)
    assert host._pg_x_saving is False
    host._save_pg_x_details_in_background(*args)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors == [], dialogs.errors
    assert row_of(shared, "PG-X", "5")["Bagno"] == "B9"


def test_a_row_action_can_be_repeated_after_its_result_was_dropped(root, monkeypatch, shared):
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    calls = Calls()
    KEEP.append(calls)
    args = (root, "delete", ["5"], "PG-X", {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild)
    host._pg_x_row_action_in_background(*args)
    stall(root)
    assert host._pg_x_action_running is False
    host._pg_x_row_action_in_background(*args)                                        # deleted by the first run already: 0 rows now
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.infos[-1] == ("PG-X", "0 row(s) deleted.")
    assert "5" not in keys(shared, "PG-X")


def test_delete_shipped_colours_can_be_repeated_after_its_result_was_dropped(root, monkeypatch, shared):
    import gui.tabs.shared_order_actions as actions
    import parsers.situazione_loaders as loaders
    dialogs = Quiet(monkeypatch)
    monkeypatch.setattr(actions, "source_path", lambda *a, **k: "uscita.xlsx")
    monkeypatch.setattr(loaders, "load_uscita", lambda path: (pd.DataFrame({"partita": ["5"]}), []))
    host = UploadHost(root, shared, STOCK)
    calls = Calls()
    KEEP.append(calls)
    records = {"PG-X-0": sw.load_create_excel_records(shared, sheet_name="PG-X")[0]}
    sheets = {"PG-X-0": "PG-X"}
    args = (root, "PG-X", records, sheets, {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild)
    host._delete_shipped_colors(*args)
    stall(root)
    assert host._delete_shipped_running is False
    host._delete_shipped_colors(*args)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors == [], dialogs.errors
    assert dialogs.asked and "have already been shipped" in dialogs.asked[0][1]
