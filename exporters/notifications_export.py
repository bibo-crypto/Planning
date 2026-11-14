"""Write notifications to an Excel file.  One job: turn a list of notification dicts into a workbook."""
from __future__ import annotations

from collections.abc import Iterable, Sequence
from copy import copy

from utility.excel_io import safe_save_workbook


def _row(item: dict, columns: Sequence[tuple]) -> tuple:
    return tuple(item.get(field, "Other" if field == "category" else "") for field, *_ in columns)


def export_notifications_to_excel(items: Iterable[dict], path, columns: Sequence[tuple]) -> None:
    """Save *items* to *path*: one sheet "Notifications", a bold header row from *columns*, filter and frozen header.

    *columns* is a sequence of ``(stored field, header, ...)`` tuples (the Notifications table definition), so
    this module does not depend on the window that owns that definition.
    """
    from openpyxl import Workbook

    workbook = Workbook()
    try:
        sheet = workbook.active
        sheet.title = "Notifications"
        sheet.append(tuple(title for _field, title, *_ in columns))
        for item in items:
            sheet.append(_row(item, columns))
        sheet.freeze_panes = "A2"
        sheet.auto_filter.ref = sheet.dimensions
        for cell in sheet[1]:
            header_font = copy(cell.font)          # Font.copy(bold=True) is deprecated in openpyxl
            header_font.bold = True
            cell.font = header_font
        safe_save_workbook(workbook, path)
    finally:
        workbook.close()
