"""Helpers for the Overview ticket tables: columns sized to their content, the rows
formatted once, a debounced search.

Single responsibility: everything about *showing a table of rows in a Treeview*
that the Overview's two ticket windows (a card's list and a machine's schedule)
used to do separately -- and slowly, re-formatting every cell and re-joining every
row's text on each keystroke.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import font as tkfont, ttk
from typing import Any, Callable, Iterable, Sequence

import pandas as pd

MIN_COLUMN_WIDTH = 70       # a column never gets narrower than this (px)
MAX_COLUMN_WIDTH = 380      # ... nor wider: long comments are cut, not allowed to push the table
CELL_PADDING = 26           # room around the text
HEADING_PADDING = 34        # heading text + the sort click area


def _display(value: Any) -> Any:
    """What a cell shows: blank for None / NaN, everything else unchanged."""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return value


class TableModel:
    """The rows of a table, converted for display once.

    ``load`` formats every row a single time and keeps its lower-cased text next to
    it, so ``visible`` (one call per search) is a plain substring test over a list.
    """

    def __init__(self, columns: Sequence[str]) -> None:
        self.columns = list(columns)
        self.rows: list[tuple] = []
        self._blobs: list[str] = []

    def load(self, frame: pd.DataFrame) -> None:
        columns = [c for c in self.columns if c in frame.columns]
        source = frame.reindex(columns=self.columns) if len(columns) != len(self.columns) else frame[self.columns]
        self.rows = [tuple(_display(v) for v in row) for row in source.itertuples(index=False, name=None)]
        self._blobs = [" ".join(str(v) for v in row).casefold() for row in self.rows]

    def visible(self, term: str) -> list[tuple]:
        """Rows whose text contains ``term`` (case-insensitive); every row when blank."""
        needle = (term or "").strip().casefold()
        if not needle:
            return self.rows
        return [row for row, blob in zip(self.rows, self._blobs) if needle in blob]


def fit_columns(
    tree: ttk.Treeview,
    columns: Sequence[str],
    rows: Iterable[Sequence[Any]],
    *,
    sample_rows: int = 800,
    min_width: int = MIN_COLUMN_WIDTH,
    max_width: int = MAX_COLUMN_WIDTH,
    fill: bool = True,
) -> dict[str, int]:
    """Size each column to its header and its data, within [min_width, max_width], then
    spread the window's spare width over all the columns.

    A column holding short values stays narrow however wide its default was; one holding
    long text grows (up to max_width).  Only the longest few strings of each column are
    measured, so 10,000 rows cost the same as 800.

    With ``fill`` the columns are *stretched in proportion* whenever they add up to less
    than the table's width, so a table with few columns fills the window instead of
    hugging its left edge.
    The spare width is shared EQUALLY by the columns (not by their size), so a table with
    few columns ends up with comfortable, similar-looking columns; every column is centred.
    The stretch follows the window when it is resized.  Returns the fitted (natural) widths.
    """
    style = ttk.Style(tree)
    style_font = style.lookup("Treeview", "font") or "TkDefaultFont"
    body_font = tkfont.Font(root=tree, font=style_font)
    heading_font = tkfont.Font(root=tree, font=style.lookup("Treeview.Heading", "font") or style_font)

    rows = list(rows)
    if len(rows) > sample_rows:
        step = len(rows) / sample_rows
        rows = [rows[int(i * step)] for i in range(sample_rows)]

    widths: dict[str, int] = {}
    for index, column in enumerate(columns):
        header = str(tree.heading(column, "text") or column)
        longest = sorted((str(row[index]) for row in rows if index < len(row)), key=len, reverse=True)[:5]
        text_width = max((body_font.measure(text) + CELL_PADDING for text in longest), default=0)
        width = max(heading_font.measure(header) + HEADING_PADDING, text_width)
        widths[column] = max(min_width, min(max_width, width))

    def apply(available: int = 0) -> None:
        """Set the column widths: the natural ones, plus an equal share of any spare width."""
        total = sum(widths.values())
        extra = max(0, available - total) if (fill and columns) else 0
        base, remainder = divmod(extra, len(columns) or 1)
        for position, column in enumerate(columns):
            width = widths[column] + base + (1 if position < remainder else 0)
            tree.column(
                column, width=width, minwidth=min(widths[column], min_width),
                stretch=bool(fill), anchor="center",
            )

    apply()
    if fill and columns:
        last_applied = [0]

        def on_resize(event: tk.Event) -> None:
            # the visible table width: the widget width minus the vertical scrollbar's share
            available = max(0, int(event.width) - 4)
            if abs(available - last_applied[0]) > 2:
                last_applied[0] = available
                apply(available)

        tree.bind("<Configure>", on_resize, add="+")
    return widths


def debounced(widget: tk.Misc, callback: Callable[[], None], delay_ms: int = 150) -> Callable[..., None]:
    """A function that runs ``callback`` once, ``delay_ms`` after the last time it was called.

    Typing "ELVY" into a search box then re-draws the table once instead of four times.
    """
    pending: list[str | None] = [None]

    def fire() -> None:
        pending[0] = None
        callback()

    def call(*_args: Any) -> None:
        if pending[0] is not None:
            try:
                widget.after_cancel(pending[0])
            except tk.TclError:
                pass
        try:
            pending[0] = widget.after(delay_ms, fire)
        except tk.TclError:
            pending[0] = None                # the window is gone: nothing left to redraw

    return call
