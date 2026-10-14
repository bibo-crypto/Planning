"""Data Elvy lives inside Master Data (it used to be a top-level page)."""
import ast
import time
from pathlib import Path

import pytest

tk = pytest.importorskip("tkinter")
from tkinter import messagebox, ttk  # noqa: E402

PROJECT = Path(__file__).resolve().parent.parent


@pytest.fixture
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display available")
    window.withdraw()
    yield window
    window.destroy()


@pytest.fixture
def isolated_master_data(tmp_path, monkeypatch):
    """Keep the master-data JSON and the Elvy mapping out of the real settings folder."""
    from parsers import elvy_mapping
    from utility import master_data

    monkeypatch.setattr(elvy_mapping, "MAPPING_FILE", tmp_path / "elvy_mapping.json")
    (tmp_path / "elvy_mapping.json").write_text("{}", encoding="utf-8")      # skip the first-run default entries
    if hasattr(master_data, "DATA_FILE"):
        monkeypatch.setattr(master_data, "DATA_FILE", tmp_path / "master_data.json")
    elif hasattr(master_data, "FILE"):
        monkeypatch.setattr(master_data, "FILE", tmp_path / "master_data.json")
    return tmp_path


def _tab_labels(book):
    return [book.tab(tab_id, "text") for tab_id in book.tabs()]


# ---------------------------------------------------------------- Master Data

def test_master_data_shows_pages_contributed_by_the_application(root, isolated_master_data):
    from gui.tabs.master_data_tab import MasterDataTab

    built = []
    tab = MasterDataTab(root, extra_pages=[("Data Elvy", lambda page: built.append(page))])

    labels = _tab_labels(tab.book)
    assert "Data Elvy" in labels
    assert labels.index("Data Elvy") < labels.index("Category Review")     # with the data pages, not after the review tool
    assert built == [tab.extra_page_frames["Data Elvy"]]
    assert labels[:len(tab.SCHEMAS)] == list(tab.SCHEMAS)                  # the existing pages are untouched


def test_a_page_that_fails_to_build_does_not_break_master_data(root, isolated_master_data):
    from gui.tabs.master_data_tab import MasterDataTab

    def broken(page):
        raise RuntimeError("boom")

    tab = MasterDataTab(root, extra_pages=[("Broken", broken), ("Fine", lambda page: ttk.Label(page, text="ok").pack())])

    labels = _tab_labels(tab.book)
    assert {"Broken", "Fine", "Category Review"} <= set(labels)
    broken_children = tab.extra_page_frames["Broken"].winfo_children()
    assert broken_children and "could not be loaded" in broken_children[0].cget("text")


def test_master_data_without_extra_pages_is_unchanged(root, isolated_master_data):
    from gui.tabs.master_data_tab import MasterDataTab

    tab = MasterDataTab(root)

    assert "Data Elvy" not in _tab_labels(tab.book)
    assert tab.extra_page_frames == {}


# ---------------------------------------------------------------- the real Data Elvy page, inside Master Data

class ElvyHost:
    """The slice of ConverterApp that the Data Elvy page uses (its methods are copied from the app)."""


def _elvy_host():
    from gui.gui import ConverterApp

    for name in ("_build_elvy_tab", "_refresh_elvy_tree", "_on_elvy_sort", "_on_elvy_save", "_on_elvy_edit",
                 "_on_elvy_delete"):
        setattr(ElvyHost, name, getattr(ConverterApp, name))
    return ElvyHost()


def _find(widget, cls):
    found = []
    for child in widget.winfo_children():
        if isinstance(child, cls):
            found.append(child)
        found.extend(_find(child, cls))
    return found


def test_data_elvy_page_works_inside_master_data(root, isolated_master_data, monkeypatch):
    from gui.tabs.master_data_tab import MasterDataTab
    from parsers.elvy_mapping import load_elvy_mapping

    monkeypatch.setattr(messagebox, "showwarning", lambda *a, **k: None)
    monkeypatch.setattr(messagebox, "showinfo", lambda *a, **k: None)
    host = _elvy_host()
    tab = MasterDataTab(root, extra_pages=[("Data Elvy", host._build_elvy_tab)])
    assert "Data Elvy" in _tab_labels(tab.book)

    host._elvy_entry_elvy.insert(0, "ART-100")
    host._elvy_entry_delta.insert(0, "C130027S")
    host._on_elvy_save()
    assert load_elvy_mapping() == {"ART-100": "C130027S"}
    assert [host._elvy_tree.item(i, "values") for i in host._elvy_tree.get_children()] == [("ART-100", "C130027S")]

    host._elvy_tree.selection_set(host._elvy_tree.get_children()[0])
    host._on_elvy_edit()                                   # rename the key: no stale duplicate may remain
    host._elvy_entry_elvy.delete(0, "end"); host._elvy_entry_elvy.insert(0, "ART-200")
    host._on_elvy_save()
    assert load_elvy_mapping() == {"ART-200": "C130027S"}

    host._elvy_tree.selection_set(host._elvy_tree.get_children()[0])
    host._on_elvy_delete()
    assert load_elvy_mapping() == {} and host._elvy_tree.get_children() == ()


# ---------------------------------------------------------------- the main window

def test_the_main_window_no_longer_has_a_top_level_data_elvy_tab_and_passes_it_to_master_data():
    tree = ast.parse((PROJECT / "gui" / "gui.py").read_text(encoding="utf-8"))
    add_calls = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "add"
        and any(isinstance(kw.value, ast.Constant) and kw.value.value == "Data Elvy" for kw in node.keywords)
    ]
    assert add_calls == []                                  # nothing adds a "Data Elvy" tab to the main notebook
    source = (PROJECT / "gui" / "gui.py").read_text(encoding="utf-8")
    assert 'extra_pages=[("Data Elvy", self._build_elvy_tab)]' in source
