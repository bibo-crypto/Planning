"""The Notifications window (gui/notifications_window.py): what each button does, with a real Tk window and a
throw-away notifications file.  Dialogs are replaced by recorders so nothing waits for a click."""
import tkinter as tk
from tkinter import filedialog, messagebox

import pytest

from gui.notifications_window import NOTIFICATION_COLUMNS, NotificationsWindow, build_resolve_warning
from tests.test_startup_pages import start_app  # noqa: F401  (fixture used by the last test)
from utility import notifications as notifications_module

PRICE = "situazione-price-mismatch:A:1:P1 (C1):4.0:7.0"
INFO = "prezzi-price-changes"


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setattr(notifications_module, "_PATH", tmp_path / "notifications.json")
    return notifications_module


@pytest.fixture
def root():
    try:
        tk_root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available for Tk: {exc}")
    tk_root.withdraw()
    yield tk_root
    try:
        tk_root.destroy()
    except tk.TclError:
        pass


class Dialogs:
    """Records every dialog and answers askyesno with ``answer``."""

    def __init__(self, monkeypatch, answer=False):
        self.answer, self.asked, self.errors, self.infos = answer, [], [], []
        monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: (self.asked.append((title, text, kw)), self.answer)[1])
        monkeypatch.setattr(messagebox, "showerror", lambda title, text, **kw: self.errors.append((title, text)))
        monkeypatch.setattr(messagebox, "showinfo", lambda title, text, **kw: self.infos.append((title, text)))


@pytest.fixture
def dialogs(monkeypatch):
    return Dialogs(monkeypatch)


def open_window(root, store, situation_tab=None):
    changed = []
    window = NotificationsWindow(root, get_situation_tab=lambda: situation_tab, on_changed=lambda: changed.append(1), store=store)
    window.changed = changed
    root.update()
    return window


def add(store, key, title="Color price differs", **fields):
    store.add_many([{"key": key, "title": title, "message": "m", "page": "Situazione Generale", "severity": "high", **fields}])


def shown(window):
    return sorted(window.tree.get_children())


def button_state(button):
    """The application's rounded buttons keep their state themselves (``_state``); a plain ttk button has cget."""
    return getattr(button, "_state", None) or str(button.cget("state"))


# ------------------------------------------------------------------ showing
def test_the_table_lists_the_open_notifications_and_updates_the_badge(root, store):
    add(store, PRICE, partita_colore="P1 (C1)")
    add(store, "system-x", "Other thing")
    window = open_window(root, store)
    assert shown(window) == sorted([PRICE, "system-x"])
    assert window.tree.item(PRICE, "values")[2] == "Color price differs"        # the Title column
    assert len(window.tree["columns"]) == len(NOTIFICATION_COLUMNS) and window.changed


def test_the_category_filter_limits_the_table(root, store):
    add(store, PRICE)
    add(store, "system-x", "Backup failed")
    window = open_window(root, store)
    window.category_var.set("System")
    window.reload()
    assert shown(window) == ["system-x"]


# ------------------------------------------------------------------ Mark Resolved
def test_an_information_notice_is_resolved_without_asking(root, store, dialogs):
    add(store, INFO, "Prices changed")
    window = open_window(root, store)
    window.tree.selection_set(INFO)
    window.resolve_selected()
    assert dialogs.asked == [] and shown(window) == [] and store.list_open() == []


def test_a_problem_still_reported_asks_first_and_No_keeps_it_open(root, store, dialogs):
    add(store, PRICE, partita_colore="P1 (C1)")
    add(store, INFO, "Prices changed")
    dialogs.answer = False
    window = open_window(root, store)
    window.tree.selection_set(PRICE, INFO)
    window.resolve_selected()

    assert len(dialogs.asked) == 1
    title, text, options = dialogs.asked[0]
    assert "still reported" in text and "Color price differs" in text and "P1 (C1)" in text
    assert options["default"] == "no" and options["icon"] == "warning"            # the safe choice is the default
    assert shown(window) == [PRICE]                                                # kept open; the notice was resolved


def test_Yes_resolves_it_and_the_next_check_does_not_reopen_it(root, store, dialogs):
    add(store, PRICE)
    dialogs.answer = True
    window = open_window(root, store)
    window.tree.selection_set(PRICE)
    window.resolve_selected()
    assert shown(window) == []

    add(store, PRICE)                                  # the next check reports the same problem
    window.reload()
    assert shown(window) == []                         # ... it stays resolved

    store.resolve_missing("situazione-price-", [])     # a check that no longer finds it
    add(store, PRICE)                                  # and later it comes back
    window.reload()
    assert shown(window) == [PRICE]


def test_a_store_that_cannot_be_updated_shows_an_error_and_keeps_the_table(root, store, dialogs, monkeypatch):
    add(store, INFO, "Prices changed")
    window = open_window(root, store)
    monkeypatch.setattr(store, "resolve", lambda key: (_ for _ in ()).throw(store.NotificationStoreError("locked")))
    window.tree.selection_set(INFO)
    window.resolve_selected()
    assert dialogs.errors and "locked" in dialogs.errors[0][1]
    assert shown(window) == [INFO]


def test_the_warning_text_handles_one_many_and_long_lists():
    one = build_resolve_warning(["A — P1"])
    assert one.startswith("This problem is still reported") and "  • A — P1" in one
    many = build_resolve_warning([f"item {i}" for i in range(8)])
    assert many.startswith("These 8 problems are") and "… and 3 more" in many and "item 4" in many and "item 5" not in many
    assert "press Refresh first" in one


# ------------------------------------------------------------------ Snooze
def test_snooze_hides_the_selected_notification(root, store, dialogs):
    add(store, PRICE)
    window = open_window(root, store)
    window.tree.selection_set(PRICE)
    window.snooze_selected()
    assert shown(window) == [] and dialogs.asked == []


# ------------------------------------------------------------------ Refresh
class FakeSituationTab:
    def __init__(self):
        self.callbacks = []

    def refresh_price_notifications_from_db(self, callback):
        self.callbacks.append(callback)


def test_refresh_without_the_situation_page_says_so(root, store, dialogs):
    window = open_window(root, store, situation_tab=None)
    window.refresh_from_sources()
    assert dialogs.errors == [("Notifications", "The current SQLite data is not available.")]


def test_refresh_disables_the_button_until_the_check_finishes(root, store, dialogs):
    tab = FakeSituationTab()
    window = open_window(root, store, tab)
    window.refresh_from_sources()
    assert button_state(window.refresh_button) == "disabled" and len(tab.callbacks) == 1
    add(store, PRICE)                                   # the check saved something
    tab.callbacks[0](None)
    assert button_state(window.refresh_button) == "normal" and shown(window) == [PRICE] and dialogs.errors == []


def test_a_failed_refresh_shows_the_error_and_still_reloads(root, store, dialogs):
    tab = FakeSituationTab()
    window = open_window(root, store, tab)
    window.refresh_from_sources()
    tab.callbacks[0](RuntimeError("Listini missing"))
    assert dialogs.errors and "Listini missing" in dialogs.errors[0][1]
    assert button_state(window.refresh_button) == "normal"


def test_a_check_that_finishes_after_the_window_was_closed_does_nothing(root, store, dialogs):
    tab = FakeSituationTab()
    window = open_window(root, store, tab)
    window.refresh_from_sources()
    window.win.destroy()
    tab.callbacks[0](RuntimeError("late"))               # must not raise
    assert dialogs.errors == []


# ------------------------------------------------------------------ Extract to Excel
def test_export_writes_the_open_notifications(root, store, dialogs, tmp_path, monkeypatch):
    from openpyxl import load_workbook
    add(store, PRICE, partita_colore="P1 (C1)")
    window = open_window(root, store)
    target = tmp_path / "out.xlsx"
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(target))
    window.export_excel()
    sheet = load_workbook(target)["Notifications"]
    assert [cell.value for cell in sheet[1]] == [col[1] for col in NOTIFICATION_COLUMNS]
    assert sheet.max_row == 2 and sheet.cell(2, 3).value == "Color price differs" and sheet.cell(2, 5).value == "P1 (C1)"
    assert sheet.cell(1, 1).font.bold and sheet.freeze_panes == "A2" and sheet.auto_filter.ref
    assert dialogs.infos and "Export completed" in dialogs.infos[0][1]


def test_export_with_nothing_open_only_informs(root, store, dialogs, monkeypatch):
    window = open_window(root, store)
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: pytest.fail("must not ask for a file"))
    window.export_excel()
    assert dialogs.infos == [("Notifications", "There are no open notifications to export.")]


def test_a_failed_export_is_shown_and_logged_with_its_traceback(root, store, dialogs, tmp_path, monkeypatch, caplog):
    add(store, PRICE)
    window = open_window(root, store)
    monkeypatch.setattr(filedialog, "asksaveasfilename", lambda **kw: str(tmp_path / "no_such_folder" / "x.xlsx"))
    import gui.notifications_window as module
    monkeypatch.setattr(module, "export_notifications_to_excel", lambda *a, **k: (_ for _ in ()).throw(PermissionError("file is open in Excel")))
    with caplog.at_level("ERROR", logger="converter"):
        window.export_excel()
    assert dialogs.errors == [("Export error", "file is open in Excel")]
    assert any(r.exc_info and r.exc_info[0] is PermissionError for r in caplog.records)


# ------------------------------------------------------------------ the application still opens it
def test_the_application_opens_the_window(start_app, store):  # noqa: F811 -- pytest fixture imported above
    app, errors, shown_errors = start_app()
    assert errors == []
    before = {str(w) for w in app.winfo_children() if isinstance(w, tk.Toplevel)}
    app._open_notifications()
    app.update()
    opened = [w for w in app.winfo_children() if isinstance(w, tk.Toplevel) and str(w) not in before]
    assert len(opened) == 1 and opened[0].title() == "Notifications"
