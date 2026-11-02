"""The "Database" menu: back up now, restore a backup, open the backups folder.

Single responsibility: the menu and its dialogs.  The work is done by utility.db_backup.
Restore opens the file chooser on the backups folder, so the planner just picks a day.
"""
from __future__ import annotations

import os
import threading
import tkinter as tk
from tkinter import filedialog, messagebox

from utility import db_backup
from utility.ui_thread import post_to_ui
from utility.utils import logger


def install_backup_menu(window: tk.Tk) -> None:
    """Add the Database menu to ``window`` and take today's backup in the background."""
    menubar = window.cget("menu")
    bar = window.nametowidget(menubar) if menubar else tk.Menu(window)
    menu = tk.Menu(bar, tearoff=False)
    menu.add_command(label="Back up now", command=lambda: _backup_now(window))
    menu.add_command(label="Restore from backup…", command=lambda: _restore(window))
    menu.add_separator()
    menu.add_command(label="Open backups folder", command=_open_folder)
    bar.add_cascade(label="Database", menu=menu)
    window.config(menu=bar)
    # Once a day, without delaying the start (nothing happens when today's copy exists).
    threading.Thread(target=db_backup.create_backup, daemon=True).start()


def _backup_now(window: tk.Tk) -> None:
    def worker() -> None:
        written = db_backup.create_backup(force=True)
        post_to_ui(window, lambda: messagebox.showinfo(
            "Backup", ("Saved:\n" + "\n".join(p.name for p in written)) if written else "Nothing to back up yet.",
            parent=window))
    threading.Thread(target=worker, daemon=True).start()


def _restore(window: tk.Tk) -> None:
    db_backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    chosen = filedialog.askopenfilename(
        parent=window, title="Choose the backup to restore", initialdir=str(db_backup.BACKUP_DIR),
        filetypes=[("Planning backups", "*.db *.sqlite3"), ("All files", "*.*")],
    )
    if not chosen:
        return
    if not messagebox.askyesno(
        "Restore backup",
        f"Replace the current database with\n{os.path.basename(chosen)} ?\n\n"
        "A copy of the current database is kept first, and the program must be restarted afterwards.",
        icon="warning", parent=window,
    ):
        return
    try:
        safety = db_backup.restore_backup(chosen)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Restore failed: %s", exc)
        messagebox.showerror("Restore backup", str(exc), parent=window)
        return
    messagebox.showinfo("Restore backup",
                        f"Restored.\nThe previous data was kept as:\n{safety.name}\n\nPlease restart Planning now.",
                        parent=window)


def _open_folder() -> None:
    db_backup.BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    try:
        os.startfile(db_backup.BACKUP_DIR)          # Windows
    except AttributeError:
        logger.info("Backups folder: %s", db_backup.BACKUP_DIR)
