"""Smart Auto-Assign, the step after the planner confirmed the suggestions: the Partita GG values are saved into the shared
workbook on a worker thread (_apply_auto_assigned_matches).  Real Tk, real thread, real workbook."""
import time
import tkinter as tk

import pandas as pd
import pytest

from tests.test_background_flags_released import KEEP, Quiet, stall
from tests.test_shared_workbook_scenarios import keys, rec, row_of
from tests.test_upload_gg_scenarios import Calls, UploadHost, pump_until, root  # noqa: F401  (fixture)
from exporters.biglietti import shared_workbook as sw

STOCK = pd.DataFrame([
    {"articolo": "G101", "partita": "159001", "mag_rocche": 40.0, "mag_peso": 80.0, "lotto": ""},
    {"articolo": "G101", "partita": "159002", "mag_rocche": 40.0, "mag_peso": 80.0, "lotto": ""},
    {"articolo": "G999", "partita": "159003", "mag_rocche": 40.0, "mag_peso": 80.0, "lotto": ""},      # another raw article
])


@pytest.fixture
def shared(tmp_path):
    path = tmp_path / "shared.xlsx"
    sw.append_create_excel(path, [rec("5", ""), rec("6", ""), rec("7", "")], "Acme")                   # all three wait in PG-X
    return path


def suggestion(partita_col, partita_gg):
    return {"partita_col": partita_col, "suggested_partita": partita_gg}


def run(root, host, suggestions):
    calls = Calls()
    KEEP.append(calls)
    calls.var.set("typed")
    host._apply_auto_assigned_matches(root, suggestions, {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild, calls.var)
    return calls


def toplevels(root):
    return [w for w in root.winfo_children() if isinstance(w, tk.Toplevel)]


def test_the_suggested_batches_are_saved_and_the_rows_stay_in_pgx_for_checking(root, monkeypatch, shared):
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    calls = run(root, host, [suggestion("5", "159001"), suggestion("6", "159002")])
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors == []
    title, text = dialogs.infos[-1]
    assert title == "Auto-Assign Complete" and "Assigned Partita GG for 2 row(s)" in text and "they stay in PG-X" in text
    assert row_of(shared, "PG-X", "5")["Partita GG"] == "159001" and row_of(shared, "PG-X", "6")["Partita GG"] == "159002"
    assert keys(shared, "Orders") == [] and sorted(keys(shared, "PG-X")) == ["5", "6", "7"]          # nothing moved to Orders
    assert row_of(shared, "PG-X", "7")["Partita GG"] in (None, "")                                    # the row not chosen is untouched
    assert len(calls.refreshed) == 1 and set(calls.refreshed[0]) == {"Orders", "PG-X"} and calls.rebuilt == [True] and calls.var.get() == ""
    assert toplevels(root) == []                                                                     # the "Assigning Stock..." window is gone


def test_a_suggestion_of_the_wrong_raw_article_is_never_accepted(root, monkeypatch, shared):
    dialogs = Quiet(monkeypatch)
    notified = []
    host = UploadHost(root, shared, STOCK)
    host._on_notification = lambda *args: notified.append(args)
    calls = run(root, host, [suggestion("5", "159003")])                                            # stock of G999 for a colour that needs G101
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.infos == [] and dialogs.errors[0][0] == "Auto-Assign Error"
    assert "does not belong to article G101" in dialogs.errors[0][1]
    assert row_of(shared, "PG-X", "5")["Partita GG"] in (None, "")                                    # nothing was saved
    assert notified and notified[0][0] == "pgx-save-error" and notified[0][3] == "Shared Orders"    # the planner is also notified
    assert calls.refreshed == [] and toplevels(root) == []


def test_a_workbook_that_is_open_in_excel_gives_a_clear_message(root, monkeypatch, shared):
    from utility import excel_io
    dialogs = Quiet(monkeypatch)
    notified = []
    host = UploadHost(root, shared, STOCK)
    host._on_notification = lambda *args: notified.append(args)

    def locked(*_a, **_k):
        raise PermissionError("[WinError 32] used by another process")

    monkeypatch.setattr(excel_io.os, "replace", locked)
    before = shared.read_bytes()
    run(root, host, [suggestion("5", "159001")])
    assert pump_until(root, lambda: dialogs.errors)
    assert "The Excel file is open or locked. Close it in Excel" in dialogs.errors[0][1]
    assert notified and notified[0][0] == "pgx-save-error"
    assert shared.read_bytes() == before                                                              # the workbook is untouched


def test_when_a_later_suggestion_fails_the_earlier_ones_stay_saved(root, monkeypatch, shared):
    """Current behaviour, documented: rows are saved one by one, so a failure part-way leaves the earlier rows assigned."""
    dialogs = Quiet(monkeypatch)
    host = UploadHost(root, shared, STOCK)
    run(root, host, [suggestion("5", "159001"), suggestion("6", "159003")])                         # the second one is the wrong article
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.errors and "does not belong to article" in dialogs.errors[0][1]
    assert row_of(shared, "PG-X", "5")["Partita GG"] == "159001" and row_of(shared, "PG-X", "6")["Partita GG"] in (None, "")
