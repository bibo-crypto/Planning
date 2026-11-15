"""Characterisation tests of the "Select Orders for Biglietti" window (gui/tabs/shared_orders_window.py).

The window is a 550-line method full of closures.  These tests open the real window on synthetic records and pin what the
user sees and what its buttons do, so the method can be taken apart safely.  Actions that would touch the shared Excel
or SQLite (delete / move / save / print) are recorded, never run.
"""
import tkinter as tk
from datetime import datetime
from tkinter import messagebox, ttk

import pytest

from exporters.biglietti.records import OrderRecord
from gui.tabs.shared_orders_window import SharedOrdersWindowMixin


def record(partita, customer="Acme", article="C101", **fields):
    base = dict(customer_code="1001", customer_name=customer, article=article, description="", additional_raw="",
                color_code="C1", color_name="Red", order_no="O-1", order_row="1", colored_batch=partita, raw_batch="",
                quantity_cones=10, raw_weight=None, dispo="D1", bagno="B1")
    base.update(fields)
    return OrderRecord(**base)


class Host(SharedOrdersWindowMixin, tk.Frame):
    """Just enough of BigliettiTab for the window: a widget plus recorders for everything the buttons delegate to."""

    def __init__(self, master):
        super().__init__(master)
        self.calls = []

    def _record(self, name):
        return lambda *args, **kwargs: self.calls.append((name, args, kwargs))

    def __getattr__(self, name):
        if name in {"_pg_x_row_action_in_background", "_delete_shipped_colors", "_print_assigned_pgx", "_print_selected_shared",
                    "_smart_auto_assign_pg_x", "_upload_pgx_gg_file", "_save_pg_x_in_background", "_save_pg_x_details_in_background"}:
            return self._record(name)
        raise AttributeError(name)


class Dialogs:
    def __init__(self, monkeypatch, answer=True):
        self.answer, self.warnings, self.asked = answer, [], []
        monkeypatch.setattr(messagebox, "showwarning", lambda title, text, **kw: self.warnings.append((title, text)))
        monkeypatch.setattr(messagebox, "askyesno", lambda title, text, **kw: (self.asked.append((title, text)), self.answer)[1])


@pytest.fixture
def root(monkeypatch):
    try:
        tk_root = tk.Tk()
    except tk.TclError as exc:
        pytest.skip(f"no display available for Tk: {exc}")
    monkeypatch.setattr(tk.Toplevel, "grab_set", lambda self: None)      # the real window grabs input; not needed (or possible) here
    tk_root.geometry("1200x700+0+0")
    tk_root.update()
    yield tk_root
    try:
        tk_root.destroy()
    except tk.TclError:
        pass


@pytest.fixture
def dialogs(monkeypatch):
    return Dialogs(monkeypatch)


def datasets():
    return {
        "Orders": [record("10", "Zeta"),
                   record("2", "Acme", delivery="2026-11-14"), record("abc", "Mid"), record("1", "Beta", delivery=datetime(2026, 12, 1)),
                   record("5", "MED srl", customer_code="3004", additional_raw="a-b-c-d-POLMON 77-e")],
        "PG-X": [record("30", "PgxOne"), record("31", "PgxTwo")],
    }


def open_window(root, data=None):
    host = Host(root)
    host.pack()
    data = data if data is not None else datasets()
    host._open_shared_orders_window(data)
    root.update()
    window = [w for w in host.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    window.data = data
    window.host = host
    window.update()
    return window


def walk(widget):
    for child in widget.winfo_children():
        yield child
        yield from walk(child)


def tree_of(window):
    return next(w for w in walk(window) if isinstance(w, ttk.Treeview))


def notebook_of(window):
    return next(w for w in walk(window) if isinstance(w, ttk.Notebook))


def entries_of(window):
    return [w for w in walk(window) if isinstance(w, ttk.Entry)]          # [search box, Partita GG box]


def button_text(widget):
    return getattr(widget, "_text", None) or (str(widget.cget("text")) if "text" in widget.keys() else None)


def click(window, label):
    for widget in walk(window):
        if button_text(widget) == label:
            command = getattr(widget, "_command", None)
            if command is None:
                widget.invoke()
            else:
                command()
            window.update()
            return
    raise AssertionError(f"no button labelled {label!r}")


def shown(window):
    tree = tree_of(window)
    return [tree.item(iid, "values") for iid in tree.get_children()]


def cell(values, column_name):
    from gui.tabs.shared_order_logic import ORDER_TABLE_COLUMNS
    return values[1 + ORDER_TABLE_COLUMNS.index(column_name)]


def select_sheet(window, index):
    notebook_of(window).select(index)
    window.update()
    window.update_idletasks()


# ------------------------------------------------------------------ what is shown
def test_the_orders_page_lists_only_orders_sorted_by_partita_as_numbers(root):
    window = open_window(root)
    batches = [cell(values, "Partita Col") for values in shown(window)]
    assert batches == ["1", "2", "5", "10", "abc"]                          # numbers first, then text
    assert len(shown(window)) == 5 and all(values[0] == "☐" for values in shown(window))
    assert "30" not in batches                                              # PG-X rows are on the other page


def test_cells_show_dates_dd_mm_yyyy_and_the_polmon_of_med_orders(root):
    window = open_window(root)
    rows = {cell(values, "Partita Col"): values for values in shown(window)}
    assert cell(rows["2"], "Consegna") == "14/11/2026" and cell(rows["1"], "Consegna") == "01/12/2026"
    assert cell(rows["5"], "POLMON") == "POLMON 77" and cell(rows["10"], "POLMON") == ""


def test_the_page_has_the_print_column_and_all_excel_columns(root):
    tree = tree_of(open_window(root))
    assert len(tree["columns"]) == 26 and tree.heading("select")["text"] == "Print"
    assert tree.heading("excel_1")["text"] == "Cliente" and tree.heading("excel_11")["text"] == "Partita Col"


# ------------------------------------------------------------------ search and sort
def test_search_filters_rows_ignoring_case_and_clear_shows_everything_again(root):
    window = open_window(root)
    search = entries_of(window)[0]
    search.insert(0, "acme")
    window.update()
    assert [cell(values, "Cliente") for values in shown(window)] == ["Acme"]
    search.delete(0, "end")
    search.insert(0, "zzz-no-such-text")
    window.update()
    assert shown(window) == []
    click(window, "Clear")
    assert len(shown(window)) == 5


def test_clicking_a_heading_sorts_by_it_and_clicking_again_reverses(root):
    window = open_window(root)
    tree = tree_of(window)
    heading_command = tree.heading("excel_1")["command"]                    # "Cliente"
    window.tk.eval(heading_command)
    window.update()
    assert [cell(v, "Cliente") for v in shown(window)] == ["Acme", "Beta", "MED srl", "Mid", "Zeta"]
    window.tk.eval(heading_command)
    window.update()
    assert [cell(v, "Cliente") for v in shown(window)] == ["Zeta", "Mid", "MED srl", "Beta", "Acme"]


def test_switching_to_the_pgx_page_shows_its_rows_and_clears_the_search(root):
    window = open_window(root)
    entries_of(window)[0].insert(0, "acme")
    window.update()
    select_sheet(window, 1)
    assert [cell(v, "Partita Col") for v in shown(window)] == ["30", "31"]
    assert entries_of(window)[0].get() == ""
    select_sheet(window, 0)
    assert len(shown(window)) == 5


# ------------------------------------------------------------------ the print tick-box
def test_a_click_on_the_print_cell_ticks_the_row_after_the_double_click_delay(root):
    window = open_window(root)
    tree = tree_of(window)
    iid = tree.get_children()[0]
    x, y, width, height = tree.bbox(iid, "#1")
    tree.event_generate("<ButtonRelease-1>", x=x + width // 2, y=y + height // 2)
    window.update()
    assert tree.item(iid, "values")[0] == "☐"                                # not yet: a double-click could still follow
    window.after(450, lambda: None)
    end = datetime.now().timestamp() + 0.8
    while datetime.now().timestamp() < end:
        window.update()
    assert tree.item(iid, "values")[0] == "☑"


def test_a_click_outside_the_print_column_does_not_tick_anything(root):
    window = open_window(root)
    tree = tree_of(window)
    iid = tree.get_children()[0]
    x, y, width, height = tree.bbox(iid, "#2")
    tree.event_generate("<ButtonRelease-1>", x=x + width // 2, y=y + height // 2)
    end = datetime.now().timestamp() + 0.6
    while datetime.now().timestamp() < end:
        window.update()
    assert all(values[0] == "☐" for values in shown(window))


# ------------------------------------------------------------------ buttons
def test_delete_without_a_selection_only_warns(root, dialogs):
    window = open_window(root)
    click(window, "Delete")
    assert dialogs.warnings == [("No Row Selected", "Select one or more rows first.")] and window.host.calls == []


def test_delete_asks_first_and_runs_nothing_when_the_answer_is_no(root, dialogs):
    window = open_window(root)
    tree = tree_of(window)
    tree.selection_set(tree.get_children()[:2])
    dialogs.answer = False
    click(window, "Delete")
    assert dialogs.asked and dialogs.asked[0][0] == "Delete Orders Rows" and "2 selected Orders row(s)" in dialogs.asked[0][1]
    assert window.host.calls == []


def test_delete_confirmed_hands_the_selected_batches_to_the_background_action(root, dialogs):
    window = open_window(root)
    tree = tree_of(window)
    tree.selection_set(tree.get_children()[:2])                              # batches "1" and "2" (sorted order)
    click(window, "Delete")
    name, args, _kwargs = window.host.calls[-1]
    assert name == "_pg_x_row_action_in_background"
    assert args[1] == "delete" and args[2] == ["1", "2"] and args[3] == "Orders" and args[4] is window.data


def test_send_to_orders_is_only_for_the_pgx_page(root, dialogs):
    window = open_window(root)
    click(window, "Send to Orders")
    assert dialogs.warnings == [("PG-X Only", "This action is available only on the PG-X page.")]


def test_send_to_orders_without_raw_yarn_asks_before_moving(root, dialogs):
    window = open_window(root)
    select_sheet(window, 1)
    tree = tree_of(window)
    tree.selection_set(tree.get_children()[0])
    dialogs.answer = False
    click(window, "Send to Orders")
    assert dialogs.asked and dialogs.asked[0][0] == "No Raw Yarn Assigned" and window.host.calls == []
    dialogs.answer = True
    click(window, "Send to Orders")
    assert window.host.calls[-1][0] == "_pg_x_row_action_in_background" and window.host.calls[-1][1][1] == "move"


def test_save_partita_gg_needs_the_pgx_page_and_both_fields(root, dialogs):
    window = open_window(root)
    click(window, "SAVE")
    assert dialogs.warnings[-1][0] == "PG-X Only"
    select_sheet(window, 1)
    click(window, "SAVE")
    assert dialogs.warnings[-1][0] == "Missing Data" and window.host.calls == []
    entries_of(window)[0].insert(0, "30")
    entries_of(window)[1].insert(0, "G-77")
    click(window, "SAVE")
    assert window.host.calls[-1][0] == "_save_pg_x_in_background" and window.host.calls[-1][1][1:3] == ("30", "G-77")


# ------------------------------------------------------------------ the row editor (double-click on a row)
import time  # noqa: E402

import pandas as pd  # noqa: E402


def _stock_summary():
    return pd.DataFrame([
        {"articolo": "G101", "partita": "12", "mag_rocche": 40.0},        # the raw article colour C101 needs
        {"articolo": "G999", "partita": "13", "mag_rocche": 5.0},         # a different raw article
    ])


def double_click(tree, x, y):
    """Tk refuses event_generate("<Double-1>"); two quick press/release pairs are what the mouse really sends."""
    for _ in range(2):
        tree.event_generate("<ButtonPress-1>", x=x, y=y)
        tree.event_generate("<ButtonRelease-1>", x=x, y=y)


def pump(window, seconds):
    """Run the real Tk main loop for a moment.

    Worker threads hand their result over with widget.after(); tkinter only accepts that from another thread while
    the main loop is running (otherwise "main thread is not in main loop" and post_to_ui drops the result), so a plain
    update() loop would never see the Magazino stock arrive.
    """
    window.after(int(seconds * 1000), window.quit)
    window.mainloop()


def press(widget):
    command = getattr(widget, "_command", None)
    command() if command else widget.invoke()


def open_editor(root, monkeypatch, summary=None):
    """Open the window, double-click the first Orders row (batch "1", article C101) and wait for Magazino to load."""
    monkeypatch.setattr(Host, "_load_common_sources", lambda self: (None, None, None, None, _stock_summary() if summary is None else summary), raising=False)
    window = open_window(root)
    tree = tree_of(window)
    iid = tree.get_children()[0]
    x, y, width, height = tree.bbox(iid, "#3")
    double_click(tree, x + width // 2, y + height // 2)
    window.update()
    editor = [w for w in window.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    status = next(w for w in walk(editor) if isinstance(w, ttk.Label) and "textvariable" in w.keys() and str(w.cget("textvariable")))
    editor.status, editor.window = status, window
    editor.fields = [w for w in walk(editor) if isinstance(w, (ttk.Combobox, ttk.Entry))]   # Articolo, Titolo, Partita GG, Bagno, Rocche, M/C
    end = time.time() + 10
    while "loading Magazino" in editor.getvar(str(status.cget("textvariable"))) and time.time() < end:
        pump(window, 0.05)
    assert "loading Magazino" not in editor.getvar(str(status.cget("textvariable")))
    return editor


def status_text(editor):
    return editor.getvar(str(editor.status.cget("textvariable")))


def type_partita(editor, text):
    box = editor.fields[2]
    box.delete(0, "end")
    box.insert(0, text)
    box.event_generate("<KeyRelease>")
    editor.update()


def test_the_editor_opens_with_the_rows_values_and_loads_magazino(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    assert editor.title() == "Edit Orders Color"
    assert [box.get() for box in editor.fields][:2] == ["C101", ""]                         # Articolo, Titolo
    assert status_text(editor) == "Partita GG is blank — the row will remain in PG-X" or status_text(editor).startswith("Expected raw article: G101")


def test_the_editor_shows_stock_of_the_right_raw_article_in_green(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    type_partita(editor, "12")
    assert status_text(editor) == "Available: 40 rocche — raw article: G101"
    assert str(editor.status.cget("foreground")) == "#2e7d32"


def test_the_editor_flags_a_wrong_raw_article_and_an_unknown_partita_in_red(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    type_partita(editor, "13")
    assert status_text(editor) == "Wrong article. Expected G101, found G999 (5 rocche)" and str(editor.status.cget("foreground")) == "#c62828"
    type_partita(editor, "99")
    assert status_text(editor) == "Expected raw article: G101 — Partita not found"
    type_partita(editor, "")
    assert status_text(editor) == "Partita GG is blank — the row will remain in PG-X" and str(editor.status.cget("foreground")) == "#666666"


def test_the_editor_refreshes_availability_when_the_partita_value_changes(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    partita = editor.fields[2]

    partita.insert(0, "12")
    assert status_text(editor) == "Available: 40 rocche — raw article: G101"
    assert str(editor.status.cget("foreground")) == "#2e7d32"

    partita.delete(0, "end")
    partita.insert(0, "13")
    assert status_text(editor) == "Wrong article. Expected G101, found G999 (5 rocche)"
    assert str(editor.status.cget("foreground")) == "#c62828"

    partita.delete(0, "end")
    partita.insert(0, "99")
    assert status_text(editor) == "Expected raw article: G101 — Partita not found"
    assert str(editor.status.cget("foreground")) == "#c62828"


def test_saving_a_valid_partita_hands_the_values_to_the_background_save(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    window = editor.window
    type_partita(editor, "12.0")                                         # 12.0 is the same batch as 12
    press(next(w for w in walk(editor) if button_text(w) == "SAVE"))
    window.update()
    name, args, kwargs = window.host.calls[-1]
    assert name == "_save_pg_x_details_in_background" and args[1] == "1"                 # the row's Partita Col
    assert args[2]["Partita GG"] == "12.0" and args[2]["Articolo"] == "C101" and args[2]["Print"] == ""
    assert kwargs == {"sheet_name": "Orders", "allow_article_mismatch": False}
    assert not editor.winfo_exists()


def test_saving_an_unknown_partita_is_refused(root, monkeypatch, dialogs):
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda title, text, **kw: errors.append((title, text)))
    editor = open_editor(root, monkeypatch)
    type_partita(editor, "99")
    press(next(w for w in walk(editor) if button_text(w) == "SAVE"))
    assert errors == [("Partita Not Found", "This Partita GG was not found in Magazino.")]
    assert editor.winfo_exists() and editor.window.host.calls == []


def test_saving_the_wrong_raw_article_asks_and_only_saves_when_confirmed(root, monkeypatch, dialogs):
    editor = open_editor(root, monkeypatch)
    window = editor.window
    type_partita(editor, "13")
    dialogs.answer = False
    press(next(w for w in walk(editor) if button_text(w) == "SAVE"))
    assert dialogs.asked[-1][0] == "Article Mismatch" and window.host.calls == [] and editor.winfo_exists()
    dialogs.answer = True
    press(next(w for w in walk(editor) if button_text(w) == "SAVE"))
    window.update()
    assert window.host.calls[-1][2]["allow_article_mismatch"] is True


def test_saving_before_magazino_has_loaded_waits(root, monkeypatch, dialogs):
    release = {"go": False}

    def slow_sources(self):
        end = time.time() + 5
        while not release["go"] and time.time() < end:
            time.sleep(0.01)
        return (None, None, None, None, _stock_summary())

    monkeypatch.setattr(Host, "_load_common_sources", slow_sources, raising=False)
    window = open_window(root)
    tree = tree_of(window)
    iid = tree.get_children()[0]
    x, y, width, height = tree.bbox(iid, "#3")
    double_click(tree, x + width // 2, y + height // 2)
    window.update()
    editor = [w for w in window.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    fields = [w for w in walk(editor) if isinstance(w, (ttk.Combobox, ttk.Entry))]
    fields[2].insert(0, "12")
    press(next(w for w in walk(editor) if button_text(w) == "SAVE"))
    assert dialogs.warnings[-1] == ("Magazino", "Wait for Magazino availability to load.")
    release["go"] = True
    pump(window, 0.5)
