"""Overview ticket tables: columns sized to their data, rows formatted once, debounced search."""
import time
import tkinter as tk
from tkinter import ttk

import pandas as pd
import pytest

from calculate.situazione import find_price_anomalies, price_issue
from gui.tree_fit import TableModel, debounced, fit_columns


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield window
    window.destroy()


def _pump(window, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        window.update()
        time.sleep(0.01)


def _find(widget, cls):
    for child in widget.winfo_children():
        if isinstance(child, cls):
            return child
        found = _find(child, cls)
        if found:
            return found
    return None


# ---------------------------------------------------------------- TableModel
def test_table_model_blanks_missing_values_and_filters_case_insensitively():
    frame = pd.DataFrame({"a": ["ELVY", None, "MED"], "b": [1.5, float("nan"), 3]})
    model = TableModel(["a", "b"])
    model.load(frame)
    assert model.rows == [("ELVY", 1.5), ("", ""), ("MED", 3)]
    assert model.visible("") is model.rows
    assert model.visible("  elvy ") == [("ELVY", 1.5)]
    assert model.visible("zzz") == []


def test_table_model_tolerates_a_column_the_frame_lacks():
    model = TableModel(["a", "missing"])
    model.load(pd.DataFrame({"a": ["x"]}))
    assert model.rows == [("x", "")]


# ---------------------------------------------------------------- fit_columns
def test_columns_follow_their_data_not_a_fixed_width(root):
    columns = ["tiny", "long_text", "huge"]
    tree = ttk.Treeview(root, columns=columns, show="headings")
    for column in columns:
        tree.heading(column, text=column)
    rows = [("A", "x" * 40, "y" * 400), ("B", "short", "z" * 10)]
    widths = fit_columns(tree, columns, rows)
    assert widths["tiny"] < widths["long_text"] < widths["huge"]
    assert widths["tiny"] >= 70                          # never thinner than the minimum
    assert widths["huge"] == 380                         # nor wider than the maximum
    assert tree.column("huge", "stretch") and not tree.column("tiny", "stretch")   # only the last one fills


def test_a_wide_heading_widens_a_column_of_short_values(root):
    tree = ttk.Treeview(root, columns=["c"], show="headings")
    tree.heading("c", text="A rather long column heading text")
    assert fit_columns(tree, ["c"], [("1",), ("2",)])["c"] > 150


def test_fit_columns_samples_large_tables(root):
    tree = ttk.Treeview(root, columns=["c"], show="headings")
    tree.heading("c", text="c")
    rows = [(str(i),) for i in range(20000)]
    started = time.time()
    fit_columns(tree, ["c"], rows)
    assert time.time() - started < 2


# ---------------------------------------------------------------- debounced
def test_debounced_runs_once_after_the_last_call(root):
    calls = []
    run = debounced(root, lambda: calls.append(1), delay_ms=40)
    for _ in range(5):
        run()
    _pump(root, 0.3)
    assert calls == [1]


# ---------------------------------------------------------------- the two Overview windows
def test_ticket_window_fits_columns_and_searches(root):
    from gui.tabs.overview_tab import OverviewTab

    frame = ttk.Frame(root)
    df = pd.DataFrame({
        "cliente": ["ELVY", "MED", "ELVY"],
        "articolo": ["C1", "C2", "C3"],
        "comment": ["PG-X-PO-1500-2026 " + "very long comment " * 3, "ok", "ok"],
    })
    OverviewTab._open_data_ticket(frame, "Totale partite", df, ["cliente", "articolo", "comment"], "t.xlsx")
    _pump(root, 0.2)
    window = [w for w in frame.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    tree = _find(window, ttk.Treeview)
    assert tree.column("cliente", "width") < tree.column("comment", "width")
    assert len(tree.get_children()) == 3

    entry = _find(window, ttk.Entry)
    entry.insert(0, "med")
    _pump(root, 0.5)                                      # debounce, then redraw
    assert [tree.item(i, "values")[0] for i in tree.get_children()] == ["MED"]
    window.destroy()


def test_machine_window_formats_the_dates_once_for_the_whole_table(root):
    from gui.tabs.overview_tab import OverviewTab

    frame = ttk.Frame(root)
    schedule = pd.DataFrame([{
        "machine": 3, "cliente": "ELVY", "articolo": "C1", "titolo": "80/2", "codice": 790351,
        "colore": "KA-MENT 4", "ordine": "O1", "riga": 1, "partita": 159527, "rocche": 72,
        "dye_date": pd.Timestamp("2026-10-30"), "delivery_target": "2026-11-05",
        "delivery_difference": 6, "bagno": "T1200",
    }])
    OverviewTab._open_machine_schedule(frame, 3, schedule)
    _pump(root, 0.2)
    window = [w for w in frame.winfo_children() if isinstance(w, tk.Toplevel)][-1]
    tree = _find(window, ttk.Treeview)
    (item,) = tree.get_children()
    values = dict(zip(tree["columns"], tree.item(item, "values")))
    assert values["dye_date"] == "30/10/2026" and values["delivery_target"] == "05/11/2026"
    window.destroy()


# ---------------------------------------------------------------- price anomalies: same answer, much faster
def _reference_anomalies(df):
    """The original row-by-row implementation (iterrows), kept as the oracle."""
    from calculate.situazione import clean_text, listini_loaded
    available = listini_loaded(df)
    out = []
    for _, row in df.iterrows():
        articolo = str(row.get("articolo", "") or "").strip()
        if not articolo:
            continue
        issue = price_issue(row.get("prezzo"), row.get("prezzo_lisini"), available)
        if issue:
            out.append((articolo, clean_text(row.get("codice", "")), issue))
    return out


def test_fast_price_anomalies_match_the_row_by_row_version():
    import random
    random.seed(7)
    n = 3000
    df = pd.DataFrame({
        "cliente": [random.choice(["ELVY", "MED"]) for _ in range(n)],
        "articolo": [random.choice(["C1", "C2", "", None]) for _ in range(n)],
        "codice": [random.randint(1, 900) for _ in range(n)],
        "colore": ["c"] * n,
        "prezzo": [random.choice(["", "4.59", "0.01", "6,16", None, 0]) for _ in range(n)],
        "prezzo_lisini": [random.choice(["", "4.59", "6.16", None]) for _ in range(n)],
    })
    fast = [(a["articolo"], str(a["codice"]), a["issue"]) for a in find_price_anomalies(df)]
    slow = [(a, str(c), i) for a, c, i in _reference_anomalies(df)]
    assert fast == slow and fast
    started = time.time()
    find_price_anomalies(pd.concat([df] * 4, ignore_index=True))
    assert time.time() - started < 1.5                    # 12,000 rows; iterrows needed ~2 s for 4,000
