"""Upload of a "Partita Col / Partita GG" file into PG-X (SharedOrdersActionsMixin._upload_pgx_gg_file).

Real Tk widgets, real worker threads (the Tk main loop is run in short slices so results posted by the workers reach the
UI), a real uploaded Excel file and a real shared workbook.  Magazino stock is a small table.  Dialogs are recorded.
"""
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox

import pandas as pd
import pytest
from openpyxl import Workbook, load_workbook
from tests.conftest import create_tk_root

from exporters.biglietti import shared_workbook as sw
from gui.tabs.shared_order_actions import SharedOrdersActionsMixin
from tests.test_shared_workbook_scenarios import keys, rec, row_of


class UploadHost(SharedOrdersActionsMixin, tk.Frame):
    def __init__(self, master, shared_excel_path, stock):
        super().__init__(master)
        self.shared_excel_path = shared_excel_path
        self._on_notification = None
        self._logger = __import__("logging").getLogger("converter")
        self._stock = stock
        self.gate = None                                   # an Event the stock loader waits for (to hold a worker back)

    def _load_common_sources(self):
        if self.gate is not None:
            self.gate.wait(10)
        return None, None, None, None, self._stock


@pytest.fixture
def root():
    tk_root = create_tk_root()
    tk_root.withdraw()
    yield tk_root
    try:
        tk_root.destroy()
    except tk.TclError:
        pass


def pump(root, seconds):
    """Tkinter only accepts widget.after() from a worker thread while the main loop runs."""
    root.after(int(seconds * 1000), root.quit)
    root.mainloop()


def pump_until(root, condition, timeout=15):
    end = time.time() + timeout
    while not condition() and time.time() < end:
        pump(root, 0.05)
    return condition()


class Dialogs:
    def __init__(self, monkeypatch, upload_path, answer=True):
        self.answer, self.infos, self.errors, self.asked = answer, [], [], []
        monkeypatch.setattr(filedialog, "askopenfilename", lambda **kw: str(upload_path))
        monkeypatch.setattr(messagebox, "showinfo", lambda title, text, **kw: self.infos.append((title, text)))
        monkeypatch.setattr(messagebox, "showerror", lambda title, text, **kw: self.errors.append((title, text)))
        monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: (self.asked.append((title, text)), self.answer)[1])


STOCK = pd.DataFrame([
    {"articolo": "G101", "partita": "159001", "mag_rocche": 40.0, "mag_peso": 80.0, "lotto": ""},      # right raw article for C101
    {"articolo": "G999", "partita": "159002", "mag_rocche": 20.0, "mag_peso": 40.0, "lotto": ""},      # another raw article
])


@pytest.fixture
def shared(tmp_path):
    path = tmp_path / "shared.xlsx"
    sw.append_create_excel(path, [rec("5", ""), rec("6", ""), rec("7", ""), rec("9", "12")], "Acme")        # 5, 6, 7 wait in PG-X
    return path


def make_upload(tmp_path, rows, headers=("Partita Col", "Partita GG")):
    path = tmp_path / "upload.xlsx"
    wb = Workbook()
    ws = wb.active
    ws.append(list(headers))
    for row in rows:
        ws.append(list(row))
    wb.save(path)
    wb.close()
    return path


def uploaded_rows(path):
    wb = load_workbook(path)
    try:
        return [tuple(c.value for c in row) for row in wb.active.iter_rows(min_row=2)]
    finally:
        wb.close()


class Calls:
    def __init__(self):
        self.refreshed, self.rebuilt, self.var = [], [], tk.StringVar(value="typed")

    def refresh(self, datasets):
        self.refreshed.append(datasets)

    def rebuild(self):
        self.rebuilt.append(True)


def run_upload(root, host, tmp_path_unused=None):
    calls = Calls()
    host._upload_pgx_gg_file(root, {"Orders": [], "PG-X": []}, calls.refresh, calls.rebuild, calls.var)
    return calls


# ------------------------------------------------------------------ the normal flow
def test_available_batches_are_assigned_and_the_processed_rows_leave_the_uploaded_file(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(5, 159001), (6, 159002), (88, 159003), (None, None)])
    dialogs = Dialogs(monkeypatch, upload)
    host = UploadHost(root, shared, STOCK)
    calls = run_upload(root, host)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors), "the upload never finished"

    assert dialogs.errors == [] and dialogs.asked == []                                  # nothing missing: no question
    title, summary = dialogs.infos[-1]
    assert title == "PG-X Upload" and "Assigned 1 row(s)." in summary and "Removed 1 processed row(s)" in summary
    assert "6: Partita GG 159002 exists in Magazino but is not for the required raw article(s) G101; not loaded." in summary
    assert "88: no matching Partita Col remains in PG-X." in summary
    row = row_of(shared, "PG-X", "5")
    assert row["Partita GG"] == "159001" and "5" in keys(shared, "PG-X") and "5" not in keys(shared, "Orders")   # assigned, still in PG-X
    assert row_of(shared, "PG-X", "6")["Partita GG"] in (None, "")                       # the mismatching one is untouched
    assert uploaded_rows(upload) == [(6, 159002), (88, 159003)]                          # only the processed row was removed
    assert len(calls.refreshed) == 1 and set(calls.refreshed[0]) == {"Orders", "PG-X"} and calls.rebuilt == [True]
    assert host._pgx_upload_running is False


def test_a_batch_missing_from_magazino_is_loaded_only_when_the_planner_confirms(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(7, 159009)])
    dialogs = Dialogs(monkeypatch, upload, answer=True)
    host = UploadHost(root, shared, STOCK)
    run_upload(root, host)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert dialogs.asked and "Partita Col 7 / Partita GG 159009" in dialogs.asked[0][1]
    assert row_of(shared, "PG-X", "7")["Partita GG"] == "159009" and uploaded_rows(upload) == []


def test_declining_the_missing_batch_skips_it_and_keeps_it_in_the_uploaded_file(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(7, 159009), (5, 159001)])
    dialogs = Dialogs(monkeypatch, upload, answer=False)
    host = UploadHost(root, shared, STOCK)
    run_upload(root, host)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    summary = dialogs.infos[-1][1]
    assert "Assigned 1 row(s)." in summary and "7: skipped because Partita GG 159009 is not in Magazino." in summary
    assert row_of(shared, "PG-X", "7")["Partita GG"] in (None, "") and uploaded_rows(upload) == [(7, 159009)]


def test_a_file_without_the_required_headers_is_refused_with_a_clear_message(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(5, 159001)], headers=("Batch", "Something"))
    dialogs = Dialogs(monkeypatch, upload)
    host = UploadHost(root, shared, STOCK)
    run_upload(root, host)
    assert dialogs.errors == [("PG-X Upload", "The file must contain exactly the required headers: Partita Col and Partita GG.")]
    assert host._pgx_upload_running is False if hasattr(host, "_pgx_upload_running") else True
    assert row_of(shared, "PG-X", "5")["Partita GG"] in (None, "")


def test_a_file_with_no_pairs_only_informs(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(None, None), (5, None)])
    dialogs = Dialogs(monkeypatch, upload)
    run_upload(root, UploadHost(root, shared, STOCK))
    assert dialogs.infos == [("PG-X Upload", "No Partita Col/Partita GG rows were found.")]


def test_a_second_upload_while_one_is_running_is_refused(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [(5, 159001)])
    dialogs = Dialogs(monkeypatch, upload)
    host = UploadHost(root, shared, STOCK)
    host.gate = threading.Event()                                                       # hold the first upload's worker back
    run_upload(root, host)
    run_upload(root, host)
    assert dialogs.infos == [("PG-X Upload", "An upload is already running. Please wait for it to finish.")]
    host.gate.set()
    assert pump_until(root, lambda: len(dialogs.infos) == 2)


def test_the_equal_batch_numbers_match_whatever_their_format(root, monkeypatch, tmp_path, shared):
    upload = make_upload(tmp_path, [("5.0", "159001")])                                 # "5.0" is the same Partita Col as 5
    dialogs = Dialogs(monkeypatch, upload)
    run_upload(root, UploadHost(root, shared, STOCK))
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert row_of(shared, "PG-X", "5")["Partita GG"] == "159001"


# ------------------------------------------------------------------ a page that goes away during the upload
def test_closing_the_page_during_an_upload_does_not_block_later_uploads(root, monkeypatch, tmp_path, shared):
    """The worker finishes after the page was destroyed: the 'upload running' flag must be released (it used to stay True)."""
    upload = make_upload(tmp_path, [(5, 159001)])
    Dialogs(monkeypatch, upload)
    host = UploadHost(root, shared, STOCK)
    host.gate = threading.Event()
    run_upload(root, host)
    host.destroy()                                                                      # the page is closed while the worker waits
    host.gate.set()
    assert pump_until(root, lambda: host._pgx_upload_running is False, timeout=8), "the upload flag stayed set after the page was closed"


def test_a_result_that_cannot_be_delivered_to_the_ui_releases_the_upload_flag(root, monkeypatch, tmp_path, shared):
    """While the main thread is inside a modal dialog (not in mainloop) a worker cannot call widget.after(): tkinter raises
    "main thread is not in main loop".  The upload used to stay marked as running for ever, blocking every later upload."""
    upload = make_upload(tmp_path, [(5, 159001)])
    dialogs = Dialogs(monkeypatch, upload)
    host = UploadHost(root, shared, STOCK)
    run_upload(root, host)
    assert pump_until(root, lambda: host._pgx_upload_running is False, timeout=12), (
        "the flag stayed set although the result could never reach the UI"
    )
    # and a new upload is accepted afterwards
    run_upload(root, host)
    assert pump_until(root, lambda: dialogs.infos or dialogs.errors)
    assert not any("already running" in text for _title, text in dialogs.infos)
