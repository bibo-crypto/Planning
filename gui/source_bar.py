"""
source_bar.py
A row of upload buttons, side by side, for the shared input files one page needs.

  [Articoli ●] [DFM ●] [Listini ●] [Magazino ●] ...

  * a click opens the file dialog and hands the file to the program's one upload route
    (ConverterApp.upload_source), which reads it, stores it in SQLite and remembers its
    path for every other page -- nothing about the path is written on the page;
  * the dot shows the state: green = in the program, red = not uploaded yet,
    orange = being read now;  pointing at a button shows the file it came from;
  * every bar refreshes when any page uploads a file (SourceBar.refresh_all()).
"""
from __future__ import annotations

import os
import tkinter as tk
import weakref
from tkinter import filedialog, ttk
from typing import Callable, Iterable

from utility import source_hub

_GREEN, _RED, _ORANGE = "#16a34a", "#dc2626", "#f59e0b"


class _Tip:
    """Small hover card with the name of the file a source was loaded from."""

    def __init__(self, widget: tk.Widget, text: Callable[[], str]):
        self._widget, self._text, self._win = widget, text, None
        widget.bind("<Enter>", self._show, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def _show(self, _event=None) -> None:
        text = self._text()
        if not text:
            return
        self._hide()
        self._win = tk.Toplevel(self._widget)
        self._win.wm_overrideredirect(True)
        tk.Label(self._win, text=text, bg="#fffbe6", fg="#1f2937", relief="solid", borderwidth=1,
                 padx=6, pady=2, font=("Segoe UI", 9)).pack()
        x = self._widget.winfo_rootx()
        y = self._widget.winfo_rooty() + self._widget.winfo_height() + 4
        self._win.geometry(f"+{x}+{y}")

    def _hide(self, _event=None) -> None:
        if self._win is not None:
            try:
                self._win.destroy()
            except tk.TclError:
                pass
            self._win = None


class SourceBar(ttk.Frame):
    """Side-by-side upload buttons for the files a page needs."""

    _instances: "weakref.WeakSet[SourceBar]" = weakref.WeakSet()

    def __init__(self, parent, keys: Iterable[str], upload: Callable[[str, str], None], *,
                 title: str = "Files", button_width: int = 11):
        super().__init__(parent, relief="solid", borderwidth=1, padding=(4, 2))
        self._keys = [k for k in keys if k in source_hub.SOURCES]
        self._upload = upload
        self._busy: set[str] = set()
        self._dots: dict[str, tk.Label] = {}
        ttk.Label(self, text=f"{title}:", foreground="#475467").grid(row=0, column=0, padx=(2, 8))
        for column, key in enumerate(self._keys, start=1):
            cell = ttk.Frame(self)
            cell.grid(row=0, column=column, padx=3, pady=2)
            button = ttk.Button(cell, text=source_hub.button_text(key), width=button_width,
                                command=lambda k=key: self._pick(k))
            button.pack(side="left")
            dot = tk.Label(cell, text="●", font=("Segoe UI", 12), fg=_RED)
            dot.pack(side="left", padx=(2, 0))
            self._dots[key] = dot
            _Tip(button, lambda k=key: self._tip_text(k))
            _Tip(dot, lambda k=key: self._tip_text(k))
        SourceBar._instances.add(self)
        self.bind("<Map>", lambda _e: self.refresh(), add="+")
        self.refresh()

    # ------------------------------------------------------------ actions
    def _pick(self, key: str) -> None:
        current = source_hub.stored_path(key)
        path = filedialog.askopenfilename(
            parent=self,
            title=f"Select {source_hub.long_name(key)}",
            initialdir=os.path.dirname(current) if current and os.path.isdir(os.path.dirname(current)) else None,
            filetypes=[("Excel files", "*.xlsx *.xlsm *.xls"), ("All files", "*.*")],
        )
        if not path:
            return
        self.set_busy(key, True)
        try:
            self._upload(key, path)
        except Exception:  # noqa: BLE001 -- the page must stay alive; the log has the details
            self.set_busy(key, False)
            raise

    def set_busy(self, key: str, busy: bool) -> None:
        for bar in list(SourceBar._instances):
            if key in bar._dots:
                (bar._busy.add if busy else bar._busy.discard)(key)
                bar.refresh()

    # -------------------------------------------------------------- state
    def _tip_text(self, key: str) -> str:
        if key in self._busy:
            return f"{source_hub.long_name(key)} — reading the file…"
        name = source_hub.file_label(key)
        if source_hub.is_ready(key):
            return f"{source_hub.long_name(key)}\n{name}" if name else source_hub.long_name(key)
        return f"{source_hub.long_name(key)} — not uploaded yet"

    def refresh(self) -> None:
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        for key, dot in self._dots.items():
            if key in self._busy:
                colour = _ORANGE
            else:
                colour = _GREEN if source_hub.is_ready(key) else _RED
            try:
                dot.configure(fg=colour)
            except tk.TclError:
                pass

    @classmethod
    def refresh_all(cls) -> None:
        for bar in list(cls._instances):
            bar.refresh()


def attach_to_top(page: tk.Widget, bar: SourceBar) -> None:
    """Put *bar* above everything already on *page*, whichever geometry manager the page uses."""
    grid_children = page.grid_slaves()
    pack_children = [w for w in page.pack_slaves() if w is not bar]
    if pack_children and not grid_children:
        bar.pack(side="top", fill="x", padx=4, pady=(4, 2), before=pack_children[0])
        return
    for child in grid_children:
        if child is bar:
            continue
        info = child.grid_info()
        child.grid_configure(row=int(info.get("row", 0)) + 1)
    bar.grid(row=0, column=0, columnspan=8, sticky="w", padx=4, pady=(4, 2))
