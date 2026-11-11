"""Machine Timeline: Search / Zoom / Refresh and the files frame share ONE row, and nothing is cut.

The buttons are 130 px wide whatever their text, so the row needs ~1570 px; the page squeezes the
buttons (RoundedButton.set_density) just enough for the window, and only when even the tightest
sizes do not fit does the files frame drop under the buttons.  The legend sits in the status row.
"""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import pytest

from gui.modern_widgets import RoundedButton
from gui.source_bar import SourceBar
from gui.tabs.machine_timeline_tab import MachineTimelineTab
from utility import source_hub


@pytest.fixture()
def make_page(monkeypatch):
    monkeypatch.setattr(ttk, "Button", RoundedButton)          # what gui.gui does for the whole program
    windows = []

    def build(width):
        root = tk.Tk()
        windows.append(root)
        root.geometry(f"{width}x600+0+0")
        page = MachineTimelineTab(root, SimpleNamespace(loaded_frames={}, current_df=None))
        page.pack(fill="both", expand=True)
        bar = SourceBar(page._file_area, source_hub.PAGE_SOURCES["timeline"], lambda key, path: None, button_width=9)
        page.set_source_bar(bar)
        settle(root)
        return root, page

    yield build
    for root in windows:
        root.destroy()


def settle(root, rounds=25):
    for _ in range(rounds):
        root.update()
        time.sleep(0.01)


def _visible_leaves(widget):
    found = []
    for child in widget.winfo_children():
        if child.winfo_ismapped():
            if not child.winfo_children() or hasattr(child, "set_density"):
                found.append(child)
            found.extend(_visible_leaves(child))
    return found


def _problems(page):
    """Everything of the top row that sticks out of the bar or is drawn narrower than it asks for."""
    bar = page._bar
    left, right = bar.winfo_rootx(), bar.winfo_rootx() + bar.winfo_width()
    problems = []
    for widget in _visible_leaves(page._controls) + _visible_leaves(page._file_area):
        name = type(widget).__name__
        if widget.winfo_rootx() < left or widget.winfo_rootx() + widget.winfo_width() > right:
            problems.append(f"{name} outside the bar")
        if widget.winfo_width() < widget.winfo_reqwidth():
            problems.append(f"{name} squeezed")
    return problems


@pytest.mark.parametrize("width", [1920, 1600, 1366, 1280, 1100, 1000])
def test_buttons_and_files_share_one_row_and_nothing_is_cut(make_page, width):
    root, page = make_page(width)
    assert int(page._file_area.grid_info()["row"]) == 0
    assert int(page._controls.grid_info()["row"]) == 0
    assert _problems(page) == []
    assert page._refresh_button.winfo_ismapped() and page._search_entry.winfo_ismapped()


def test_the_buttons_squeeze_as_the_window_narrows(make_page):
    wide_root, wide = make_page(1920)
    narrow_root, narrow = make_page(1100)
    assert wide._refresh_button.winfo_width() > narrow._refresh_button.winfo_width()
    assert wide._search_entry.cget("width") > narrow._search_entry.cget("width")


def test_the_page_follows_a_resize_in_both_directions(make_page):
    root, page = make_page(1920)
    wide = page._refresh_button.winfo_width()
    root.geometry("1100x600+0+0")
    settle(root, 40)
    assert page._refresh_button.winfo_width() < wide and _problems(page) == []
    root.geometry("1920x600+0+0")
    settle(root, 40)
    assert page._refresh_button.winfo_width() == wide and _problems(page) == []


def test_when_nothing_fits_the_files_frame_drops_under_the_buttons_and_is_still_whole(make_page, monkeypatch):
    monkeypatch.setattr(MachineTimelineTab, "_DENSITIES", ((60, 18, True),))      # roomy buttons, narrow window
    root, page = make_page(1000)
    assert int(page._file_area.grid_info()["row"]) == 1
    assert _problems(page) == []


def test_the_legend_lives_in_the_status_row_and_a_long_message_wraps(make_page):
    root, page = make_page(1366)
    page._status.configure(text="x " * 400)
    settle(root, 40)
    assert page._legend.winfo_ismapped() and page._legend.master is page._status.master
    assert int(page._status.master.grid_info()["row"]) == 3
    assert int(page._status.cget("wraplength")) > 0
    assert page._legend.winfo_rootx() + page._legend.winfo_width() <= root.winfo_rootx() + root.winfo_width()


def test_rounded_button_density_switch():
    root = tk.Tk()
    try:
        button = RoundedButton(root, text="Clear")
        normal = int(button.cget("width"))
        assert normal == 130
        button.set_density(24)
        assert int(button.cget("width")) == button._font.measure("Clear") + 24 < normal
        button.set_density(None)
        assert int(button.cget("width")) == normal
    finally:
        root.destroy()
