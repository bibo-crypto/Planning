"""The Notifications window: a category filter, the table of open notifications and its buttons.

Split out of ConverterApp (gui/gui.py), which only opens it.  This module owns the window and what its buttons
do; the rules about notifications live in utility/notifications.py and the Excel file in
exporters/notifications_export.py.  Everything the window needs from the application is passed in
(``get_situation_tab`` and ``on_changed``), so it can be built and tested on its own.
"""
from __future__ import annotations

import tkinter as tk
from collections.abc import Callable
from tkinter import filedialog, messagebox, ttk

from exporters.notifications_export import export_notifications_to_excel
from utility import notifications
from utility.utils import bind_escape_to_close, keep_window_on_top, logger

# (stored field, header, width, centred) -- the Notifications table and its Excel export.
NOTIFICATION_COLUMNS = (
    ("severity", "Severity", 80, True), ("category", "Category", 100, False),
    ("title", "Title", 160, False), ("page", "Page", 110, True),
    ("partita_colore", "Partita Colore", 110, True), ("ordine", "Ordine", 90, True),
    ("riga", "Riga", 55, True), ("message", "Message", 270, False),
    ("created_at", "Created", 130, True),
)


def build_resolve_warning(labels: list[str], limit: int = 5) -> str:
    """The question asked before resolving problems that the latest check still reports."""
    shown = labels[:limit]
    lines = "\n".join(f"  • {label}" for label in shown)
    if len(labels) > limit:
        lines += f"\n  … and {len(labels) - limit} more"
    subject = "This problem is" if len(labels) == 1 else f"These {len(labels)} problems are"
    return (
        f"{subject} still reported by the latest check:\n\n{lines}\n\n"
        "Resolve anyway? It stays hidden until the problem goes away and later comes back "
        "(or its values change).\n\n"
        "If you already fixed it, choose No and press Refresh first."
    )


class NotificationsWindow:
    """Window + user actions: Mark Resolved, Snooze 24h, Extract to Excel, Refresh, Close."""

    def __init__(self, parent, *, get_situation_tab: Callable[[], object | None],
                 on_changed: Callable[[], None], store=notifications) -> None:
        self._store = store
        self._get_situation_tab = get_situation_tab
        self._on_changed = on_changed
        self.win = win = tk.Toplevel(parent)
        bind_escape_to_close(win)
        keep_window_on_top(win)
        win.title("Notifications")
        win.geometry("1010x380")
        win.minsize(680, 280)
        win.resizable(True, True)
        # Keep this as a normal overlapped Windows window so the native
        # Minimize, Restore/Maximize, and Close buttons are available.
        win.overrideredirect(False)
        try:
            win.wm_attributes("-toolwindow", False)
        except tk.TclError:
            pass
        win.columnconfigure(0, weight=1)
        win.rowconfigure(1, weight=1)
        self._build_filter_bar()
        self._build_table()
        self._build_buttons()
        self.reload()

    # ----------------------------------------------------------------- construction
    def _build_filter_bar(self) -> None:
        bar = ttk.Frame(self.win)
        bar.grid(row=0, column=0, sticky="ew", padx=8, pady=(8, 0))
        ttk.Label(bar, text="Category:").pack(side="left")
        self.category_var = tk.StringVar(value="All")
        self.category_combo = ttk.Combobox(bar, textvariable=self.category_var, values=("All",) + notifications.CATEGORIES,
                                           state="readonly", width=14)
        self.category_combo.pack(side="left", padx=6)
        self.category_combo.bind("<<ComboboxSelected>>", lambda _event: self.reload())

    def _build_table(self) -> None:
        self.tree = ttk.Treeview(self.win, columns=[c[0] for c in NOTIFICATION_COLUMNS], show="headings")
        for col, title, width, centred in NOTIFICATION_COLUMNS:
            self.tree.heading(col, text=title)
            self.tree.column(col, width=width, anchor="center" if centred else "w")
        self.tree.grid(row=1, column=0, columnspan=5, sticky="nsew", padx=8, pady=8)
        self.tree.tag_configure("evenrow", background="#ffffff")
        self.tree.tag_configure("oddrow", background="#eef4fb")

    def _build_buttons(self) -> None:
        win = self.win
        ttk.Button(win, text="Mark Resolved", command=self.resolve_selected).grid(row=2, column=0, sticky="w", padx=8, pady=(0, 8))
        ttk.Button(win, text="Snooze 24h", command=self.snooze_selected).grid(row=2, column=1, padx=8, pady=(0, 8))
        ttk.Button(win, text="Extract to Excel", command=self.export_excel).grid(row=2, column=2, padx=8, pady=(0, 8))
        self.refresh_button = ttk.Button(win, text="Refresh", command=self.refresh_from_sources)
        self.refresh_button.grid(row=2, column=3, padx=8, pady=(0, 8))
        ttk.Button(win, text="Close", command=win.destroy).grid(row=2, column=4, sticky="e", padx=8, pady=(0, 8))

    # ----------------------------------------------------------------- actions
    def reload(self) -> None:
        """Show the open notifications of the chosen category and update the badge."""
        self.tree.delete(*self.tree.get_children())
        for index, item in enumerate(self._store.list_open(self.category_var.get())):
            self.tree.insert(
                "", "end", iid=item["key"],
                values=tuple(item.get(col, "Other" if col == "category" else "") for col, *_ in NOTIFICATION_COLUMNS),
                tags=("oddrow" if index % 2 else "evenrow",),
            )
        self._on_changed()

    def refresh_from_sources(self) -> None:
        situation_tab = self._get_situation_tab()
        if situation_tab is None:
            messagebox.showerror("Notifications", "The current SQLite data is not available.", parent=self.win)
            return
        self.refresh_button.configure(state="disabled", text="Refreshing…")
        situation_tab.refresh_price_notifications_from_db(self._finish_source_refresh)

    def _finish_source_refresh(self, error=None) -> None:
        if not self.win.winfo_exists():
            return
        self.refresh_button.configure(state="normal", text="Refresh")
        if error is not None:
            messagebox.showerror("Notifications", f"Could not refresh price notifications:\n{error}", parent=self.win)
        self.reload()

    def resolve_selected(self) -> None:
        """Resolve the selected notifications.

        Notifications whose problem the latest check still reports are resolved only after the user confirms;
        then they stay hidden until the problem goes away (notifications.dismiss).  If the user says No they stay
        open.  The others (information notices, already-fixed problems) are resolved without asking.
        """
        selected = list(self.tree.selection())
        live = [key for key in selected if self._store.is_live(key)]
        others = [key for key in selected if key not in live]
        try:
            if live and self._confirm_resolving(live):
                for key in live:
                    self._store.dismiss(key)
            for key in others:
                self._store.resolve(key)
        except notifications.NotificationStoreError as exc:
            logger.warning("Mark Resolved failed: %s", exc)
            messagebox.showerror("Notifications", f"The notifications file could not be updated:\n{exc}", parent=self.win)
        self.reload()

    def _confirm_resolving(self, keys: list[str]) -> bool:
        by_key = {item.get("key"): item for item in self._store.list_all()}
        labels = []
        for key in keys:
            item = by_key.get(key, {})
            detail = item.get("partita_colore", "")
            labels.append(f"{item.get('title', key)}" + (f" — {detail}" if detail and detail != "N/A" else ""))
        return messagebox.askyesno("Problem still reported", build_resolve_warning(labels), icon="warning",
                                   default="no", parent=self.win)

    def snooze_selected(self) -> None:
        try:
            for key in self.tree.selection():
                self._store.snooze(key, 24)
        except notifications.NotificationStoreError as exc:
            logger.warning("Snooze failed: %s", exc)
            messagebox.showerror("Notifications", f"The notifications file could not be updated:\n{exc}", parent=self.win)
        self.reload()

    def export_excel(self) -> None:
        """Export the open notifications to an Excel file chosen by the user."""
        items = self._store.list_open()
        if not items:
            messagebox.showinfo("Notifications", "There are no open notifications to export.", parent=self.win)
            return
        path = filedialog.asksaveasfilename(
            parent=self.win, title="Export Notifications", defaultextension=".xlsx",
            filetypes=[("Excel files", "*.xlsx")], initialfile="notifications.xlsx",
        )
        if not path:
            return
        try:
            export_notifications_to_excel(items, path, NOTIFICATION_COLUMNS)
            messagebox.showinfo("Notifications", f"Export completed:\n{path}", parent=self.win)
        except Exception as exc:  # noqa: BLE001 -- shown to the user and logged with its traceback
            logger.exception("Notifications export failed")
            messagebox.showerror("Export error", str(exc), parent=self.win)
