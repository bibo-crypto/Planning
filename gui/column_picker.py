"""The "Columns…" window: tick the columns each output sheet should contain and drag them into order.

Single responsibility: show the choice and hand it to utility.column_selection.  What
can be chosen comes from exporters.column_catalog; applying it is done by the exporters.
One tab per sheet; every column is a row with a tick (click ☑/☐) that can be dragged
up or down (or moved with the ▲ ▼ buttons).  On the Biglietti pages the columns that
are also printed on the Word ticket carry a 🖨 mark.  "Save" warns first when a column
that another page (or a highlight) relies on was switched off.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import messagebox, ttk
from typing import Callable

from exporters.column_catalog import PageSpec, SheetSpec, dependency_notes, page_spec
from utility import column_selection
from utility.utils import bind_escape_to_close, keep_window_on_top

PRINT_MARK = " 🖨"
ON, OFF = "☑", "☐"
MAX_WARNING_LINES = 12


class ColumnPicker(tk.Toplevel):
    """Window for one page (see the module docstring)."""

    def __init__(self, parent: tk.Misc, page_key: str, on_saved: Callable[[], None] | None = None):
        super().__init__(parent)
        self._spec: PageSpec = page_spec(page_key)
        self._on_saved = on_saved
        self._choice = column_selection.load_hidden(page_key)
        self._trees: dict[str, ttk.Treeview] = {}
        self._labels: dict[str, dict[str, str]] = {}    # sheet -> {tree item id: column label}
        self._counters: dict[str, ttk.Label] = {}
        self._drag_item: str | None = None
        self.title(f"Columns — {self._spec.title}")
        self.minsize(560, 460)
        self.geometry("640x600")
        bind_escape_to_close(self)
        keep_window_on_top(self)
        self._build()
        self.transient(parent.winfo_toplevel())

    # ------------------------------------------------------------------ build
    def _build(self) -> None:
        root = ttk.Frame(self, padding=10)
        root.pack(fill="both", expand=True)
        ttk.Label(root, text="Tick the columns to write and drag them into the order you want.",
                  font=("Segoe UI", 10, "bold")).pack(anchor="w")
        if self._spec.note:
            ttk.Label(root, text=self._spec.note, foreground="#64748B", wraplength=590, justify="left").pack(anchor="w", pady=(2, 6))
        book = ttk.Notebook(root)
        book.pack(fill="both", expand=True, pady=(4, 8))
        self._book = book
        for sheet in self._spec.sheets:
            frame = ttk.Frame(book, padding=8)
            book.add(frame, text=sheet.title)
            self._build_sheet_tab(frame, sheet)
        buttons = ttk.Frame(root)
        buttons.pack(fill="x")
        ttk.Button(buttons, text="↺ Reset (all columns, original order)", command=self._reset).pack(side="left")
        ttk.Button(buttons, text="💾 Save", command=self._save, style="Accent.TButton").pack(side="right")
        ttk.Button(buttons, text="Cancel", command=self.destroy).pack(side="right", padx=(0, 6))

    def _ordered_labels(self, sheet: SheetSpec) -> list[str]:
        """The sheet's labels in the saved order; labels the order does not know follow in file order."""
        saved = self._choice.get(sheet.title)
        order = list(getattr(saved, "order", ()) or ())
        known = [label for label in order if label in sheet.labels]
        return known + [label for label in sheet.labels if label not in known]

    def _build_sheet_tab(self, frame: ttk.Frame, sheet: SheetSpec) -> None:
        top = ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Button(top, text="Select all", command=lambda s=sheet: self._set_all(s, True)).pack(side="left")
        ttk.Button(top, text="Clear all", command=lambda s=sheet: self._set_all(s, False)).pack(side="left", padx=6)
        ttk.Button(top, text="▼", width=3, command=lambda s=sheet: self._nudge(s, 1)).pack(side="right")
        ttk.Button(top, text="▲", width=3, command=lambda s=sheet: self._nudge(s, -1)).pack(side="right", padx=(0, 4))
        counter = ttk.Label(top, foreground="#16324F")
        counter.pack(side="right", padx=10)
        self._counters[sheet.title] = counter
        if sheet.note:
            ttk.Label(frame, text=sheet.note, foreground="#64748B", wraplength=580, justify="left").pack(anchor="w", pady=(6, 0))

        holder = ttk.Frame(frame)
        holder.pack(fill="both", expand=True, pady=(8, 0))
        tree = ttk.Treeview(holder, columns=("on", "label"), show="headings", selectmode="browse", height=16)
        tree.heading("on", text="✓"); tree.column("on", width=44, anchor="center", stretch=False)
        tree.heading("label", text="Column  (drag to reorder)"); tree.column("label", anchor="w")
        scroll = ttk.Scrollbar(holder, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=scroll.set)
        tree.pack(side="left", fill="both", expand=True)
        scroll.pack(side="right", fill="y")
        hidden = self._choice.get(sheet.title, ())
        self._labels[sheet.title] = {}
        for label in self._ordered_labels(sheet):
            text = label + (PRINT_MARK if label in sheet.ticket else "")
            item = tree.insert("", "end", values=(OFF if label in hidden else ON, text))
            self._labels[sheet.title][item] = label
        self._trees[sheet.title] = tree
        tree.bind("<ButtonPress-1>", lambda e, s=sheet: self._press(e, s))
        tree.bind("<B1-Motion>", self._drag)
        tree.bind("<ButtonRelease-1>", lambda e: setattr(self, "_drag_item", None))
        tree.bind("<space>", lambda e, s=sheet: self._toggle_selected(s))
        self._refresh_counter(sheet)

    # ----------------------------------------------------------------- state
    def _is_on(self, sheet: SheetSpec, item: str) -> bool:
        return self._trees[sheet.title].set(item, "on") == ON

    def _set_item(self, sheet: SheetSpec, item: str, value: bool) -> None:
        self._trees[sheet.title].set(item, "on", ON if value else OFF)

    def set_tick(self, sheet_title: str, label: str, value: bool) -> None:
        """Switch one column on or off by its label (also used by the tests)."""
        sheet = next(s for s in self._spec.sheets if s.title == sheet_title)
        item = next(i for i, name in self._labels[sheet_title].items() if name == label)
        self._set_item(sheet, item, value)
        self._refresh_counter(sheet)

    def _refresh_counter(self, sheet: SheetSpec) -> None:
        items = self._labels[sheet.title]
        shown = sum(1 for item in items if self._is_on(sheet, item))
        self._counters[sheet.title].config(text=f"{shown} of {len(items)} columns")

    def _set_all(self, sheet: SheetSpec, value: bool) -> None:
        for item in self._labels[sheet.title]:
            self._set_item(sheet, item, value)
        self._refresh_counter(sheet)

    def _toggle_selected(self, sheet: SheetSpec) -> None:
        for item in self._trees[sheet.title].selection():
            self._set_item(sheet, item, not self._is_on(sheet, item))
        self._refresh_counter(sheet)

    # ------------------------------------------------------------ drag & drop
    def _press(self, event, sheet: SheetSpec) -> None:
        tree = self._trees[sheet.title]
        item = tree.identify_row(event.y)
        self._drag_item = item or None
        if item and tree.identify_column(event.x) == "#1":      # click on the tick
            self._set_item(sheet, item, not self._is_on(sheet, item))
            self._refresh_counter(sheet)
            self._drag_item = None

    def _drag(self, event) -> None:
        if not self._drag_item:
            return
        tree = event.widget
        target = tree.identify_row(event.y)
        if target and target != self._drag_item:
            tree.move(self._drag_item, "", tree.index(target))
            tree.selection_set(self._drag_item)

    def _nudge(self, sheet: SheetSpec, step: int) -> None:
        tree = self._trees[sheet.title]
        for item in tree.selection():
            tree.move(item, "", max(0, tree.index(item) + step))

    # ----------------------------------------------------------------- actions
    def _reset(self) -> None:
        for sheet in self._spec.sheets:
            tree = self._trees[sheet.title]
            items = self._labels[sheet.title]
            by_label = {label: item for item, label in items.items()}
            for position, label in enumerate(sheet.labels):
                tree.move(by_label[label], "", position)
            self._set_all(sheet, True)

    def _collect(self) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        hidden: dict[str, list[str]] = {}
        order: dict[str, list[str]] = {}
        for sheet in self._spec.sheets:
            tree = self._trees[sheet.title]
            items = self._labels[sheet.title]
            labels = [items[item] for item in tree.get_children("")]
            hidden[sheet.title] = [items[i] for i in tree.get_children("") if not self._is_on(sheet, i)]
            order[sheet.title] = labels if labels != list(sheet.labels) else []
        return hidden, order

    def _warnings(self, hidden: dict[str, list[str]]) -> list[str]:
        notes = dependency_notes(self._spec.key)
        return [
            f"• {sheet} › {label}: {notes[sheet][label]}"
            for sheet, labels in hidden.items() for label in labels
            if label in notes.get(sheet, {})
        ]

    def _save(self) -> None:
        hidden, order = self._collect()
        for index, sheet in enumerate(self._spec.sheets):
            if len(hidden[sheet.title]) >= len(sheet.labels):
                self._book.select(index)
                messagebox.showwarning("Columns", f"Keep at least one column in “{sheet.title}”.", parent=self)
                return
        lines = self._warnings(hidden)
        if lines:
            shown = lines[:MAX_WARNING_LINES]
            if len(lines) > len(shown):
                shown.append(f"… and {len(lines) - len(shown)} more.")
            if not messagebox.askyesno(
                "Columns used elsewhere",
                "Switching these columns off has consequences:\n\n" + "\n".join(shown) + "\n\nSave anyway?",
                icon="warning", parent=self,
            ):
                return
        column_selection.save_hidden(self._spec.key, hidden, order)
        if self._on_saved:
            self._on_saved()
        self.destroy()


def open_column_picker(parent: tk.Misc, page_key: str, on_saved: Callable[[], None] | None = None) -> ColumnPicker:
    """Open the picker of ``page_key`` (a key of exporters.column_catalog.PAGE_KEYS)."""
    return ColumnPicker(parent, page_key, on_saved=on_saved)


def columns_button(parent: tk.Misc, page_key: str, width: int = 14) -> ttk.Button:
    """A "🗂 Columns…" button that opens the picker of ``page_key`` (the caller places it)."""
    return ttk.Button(parent, text="🗂 Columns…", width=width, command=lambda: open_column_picker(parent, page_key))
