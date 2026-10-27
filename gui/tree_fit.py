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
) -> dict[str, int]:
    """Size each column to its header and its data, within [min_width, max_width].

    A column holding short values stays narrow however wide its default was; one
    holding long text grows (up to max_width).  Only the longest few strings of each
    column are measured, so 10,000 rows cost the same as 800.  The last column is
    allowed to stretch so the table still fills a wide window.  Returns the widths.
    """
    style_font = ttk.Style(tree).lookup("Treeview", "font") or "TkDefaultFont"
    body_font = tkfont.Font(root=tree, font=style_font)
    heading_font = tkfont.Font(root=tree, font=ttk.Style(tree).lookup("Treeview.Heading", "font") or style_font)

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

    # When a report has only a few columns, content-based widths can leave a
    # large unused area on the right. Distribute that free viewport space over
    # all columns (rather than stretching only the last one), while retaining
    # the content proportions and the horizontal scrollbar for genuinely wide
    # reports. ``winfo_width`` is zero/one during initial construction, so the
    # next caller pass after geometry negotiation naturally refines the widths.
    viewport = max(0, int(tree.winfo_width()) - 4)
    required = sum(widths.values())
    fills_viewport = viewport > required and bool(widths)
    if fills_viewport:
        extra = viewport - required
        columns_count = len(widths)
        base, remainder = divmod(extra, columns_count)
        for index, column in enumerate(widths):
            widths[column] += base + (1 if index < remainder else 0)

    last = columns[-1] if columns else None
    for column, width in widths.items():
        tree.column(
            column, width=width, minwidth=min(width, min_width),
            # Once the viewport is known, either every column shares the free
            # width or none does. This prevents the old last-column balloon.
            # During construction winfo_width() can be 0/1; retain the legacy
            # last-column stretch only for that initial pass.
            stretch=(fills_viewport or (viewport <= 0 and column == last)),
            anchor="center",
        )
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
