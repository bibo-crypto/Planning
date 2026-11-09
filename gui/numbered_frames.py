"""Helpers for numbered section frames."""

from __future__ import annotations

import tkinter.font as tkfont
from tkinter import ttk


def numbered_title(parent, number: int, title: str, *, foreground: str | None = None) -> ttk.Frame:
    """Create a title with a bold number and theme-font text."""
    title_font = ttk.Style(parent).lookup("TLabelframe.Label", "font") or "TkDefaultFont"
    actual_font = tkfont.Font(root=parent, font=title_font).actual()
    number_font = (actual_font["family"], actual_font["size"], "bold")

    label = ttk.Frame(parent)
    ttk.Label(label, text=f"{number}.", font=number_font).pack(side="left", padx=(0, 4))
    ttk.Label(label, text=title, foreground=foreground).pack(side="left")
    return label


def numbered_label_frame(parent, number: int, title: str, *, padding: int = 6) -> ttk.LabelFrame:
    """Create a LabelFrame whose number is bold and whose title uses the theme font."""
    label = numbered_title(parent, number, title)
    return ttk.LabelFrame(parent, labelwidget=label, padding=padding)
