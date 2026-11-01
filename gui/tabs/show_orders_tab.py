"""The "Shared Orders" page: where the shared Create Excel workbook is chosen and used.

This used to be section 5 of the Create (EXCEL+Biglietti) page (now "Biglietti").  It is a page of its
own because everything ELVY and MED convert into (the Orders / PG-X sheets), and the
windows that work on them, hang off this one file.

The page holds no business logic: it shows the chosen workbook and forwards its
buttons to the Create page's controller (BigliettiTab), which owns the shared
workbook state and the windows (Show Orders, PG-X report, shipped history).
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import ttk
from typing import Protocol


class SharedOrdersController(Protocol):
    """What the page needs from the Create page."""
    shared_excel_path: Path | None
    shared_excel_label: ttk.Label | None

    def _pick_shared_excel(self) -> None: ...
    def _create_shared_excel(self) -> None: ...
    def _show_shared_orders(self) -> None: ...
    def _show_pgx_report(self) -> None: ...
    def _show_shipped_history(self) -> None: ...


class ShowOrdersTab(ttk.Frame):
    """Choose / create the Show Orders workbook, and open its windows."""

    def __init__(self, parent: tk.Misc, controller: SharedOrdersController) -> None:
        super().__init__(parent, padding=18)
        self._controller = controller
        self._build()
        self.refresh()

    def _build(self) -> None:
        """Title, what the page is for, the chosen workbook, and one box with the workbook
        buttons (select existing / create new) above the three actions."""
        self.columnconfigure(0, weight=1)
        ttk.Label(self, text="Shared Orders", font=("Segoe UI", 17, "bold"), foreground="#16324F").grid(row=0, column=0, sticky="w")
        ttk.Label(
            self,
            text="Shared Create Excel workbook used by ELVY and MED. Select or create it here before converting those customers.",
            foreground="#5B6B7A", wraplength=900, justify="left",
        ).grid(row=1, column=0, sticky="w", pady=(4, 14))
        self.path_label = ttk.Label(self, text="", anchor="w")
        self.path_label.grid(row=2, column=0, sticky="ew", pady=(0, 12))
        controls = ttk.LabelFrame(self, text=" Shared Create Excel workbook ", padding=12)
        controls.grid(row=3, column=0, sticky="ew")
        pick = ttk.Frame(controls)
        pick.grid(row=0, column=0, sticky="w")
        ttk.Button(pick, text="📂 Select Existing", width=20, command=self._controller._pick_shared_excel).pack(side="left", padx=(0, 6))
        ttk.Button(pick, text="➕ Create New", width=18, command=self._controller._create_shared_excel).pack(side="left")
        actions = ttk.Frame(controls)
        actions.grid(row=1, column=0, sticky="w", pady=(12, 0))
        ttk.Button(actions, text="📋 Show Orders", width=20, command=self._controller._show_shared_orders).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="📊 PG-X Orders Report", width=22, command=self._controller._show_pgx_report).pack(side="left", padx=(0, 6))
        ttk.Button(actions, text="🧾 Extract Shipped/Invoiced", width=25, command=self._controller._show_shipped_history).pack(side="left")

    def refresh(self) -> None:
        """Show the controller's current workbook path (or that none is chosen yet)."""
        path = self._controller.shared_excel_path
        if path:
            self.path_label.config(text=str(path), foreground="#111827")
        else:
            self.path_label.config(text="Not selected — ELVY/MED conversion requires this workbook", foreground="grey")
