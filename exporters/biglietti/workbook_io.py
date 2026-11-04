"""قفل الكتابة على الملفات + تنسيق شيتات الإكسل المشترك.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

import functools
import threading

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from exporters.biglietti.fields import _clean

# Every operation below reads the shared workbook, edits it in memory and saves
# it back.  Two of them running at once (e.g. a background assignment while the
# user deletes a row) would each save their own copy and one of the edits would
# be lost.  One re-entrant lock makes them run one after the other.
_WORKBOOK_WRITE_LOCK = threading.RLock()


def _serialized_workbook_write(function):
    @functools.wraps(function)
    def wrapper(*args, **kwargs):
        with _WORKBOOK_WRITE_LOCK:
            return function(*args, **kwargs)
    return wrapper


def style_sheet(
    ws,
    date_columns: tuple[str, ...] = (),
    duplicate_highlight_columns: tuple[str, ...] = (),
    range_highlight_columns: dict[str, tuple[float, float]] | None = None,
    days_until_highlight_columns: dict[str, int] | None = None,
) -> None:
    """Bold/blue header, every cell (not just the header) centered, optional
    date-only number format for the given columns, optional red highlight
    for duplicate values in the given columns (e.g. Bagno), optional red
    highlight for numbers outside a (min, max) range in the given columns
    (e.g. Densita`(360-390)), and optional red highlight for a date column
    where fewer than N days remain until that date (e.g. Delivery Date),
    recalculated live against today's date every time the file is opened."""
    fill = PatternFill("solid", fgColor="FF1F4E78")
    header = [c.value for c in ws[1]]
    last_row = ws.max_row

    thin = Side(style="thin", color="000000")
    border = Border(left=thin, right=thin, top=thin, bottom=thin)
    band_fill = PatternFill("solid", fgColor="FFDCE6F1")
    for row in ws.iter_rows():
        banded = row[0].row > 1 and (row[0].row % 2 == 0)
        for cell in row:
            cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=(cell.row == 1))
            cell.border = border
            if banded:
                cell.fill = band_fill
    for cell in ws[1]:
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = fill

    for col_name in date_columns:
        if col_name in header:
            col_idx = header.index(col_name) + 1
            for r in range(2, last_row + 1):
                ws.cell(row=r, column=col_idx).number_format = "dd/mm/yyyy"

    if last_row > 1:
        from openpyxl.formatting.rule import FormulaRule

        # Differential-format (conditional-formatting) fills render from
        # bgColor, not fgColor -- a plain PatternFill("solid", fgColor=...)
        # writes only fgColor into the dxf and Excel shows no highlight at
        # all even though the rule fires. Setting both covers it either way.
        red_fill = PatternFill(start_color="FFFFC7CE", end_color="FFFFC7CE", fill_type="solid")

        for col_name in duplicate_highlight_columns:
            if col_name in header:
                col_letter = ws.cell(row=1, column=header.index(col_name) + 1).column_letter
                rng = f"{col_letter}2:{col_letter}{last_row}"
                ws.conditional_formatting.add(
                    rng,
                    FormulaRule(
                        formula=[f'AND(${col_letter}2<>"",COUNTIF(${col_letter}$2:${col_letter}${last_row},{col_letter}2)>1)'],
                        fill=red_fill,
                        stopIfTrue=False,
                    ),
                )

        for col_name, (lo, hi) in (range_highlight_columns or {}).items():
            if col_name in header:
                col_letter = ws.cell(row=1, column=header.index(col_name) + 1).column_letter
                rng = f"{col_letter}2:{col_letter}{last_row}"
                first = f"{col_letter}2"
                formula = f'AND({first}<>"",OR({first}<{lo},{first}>{hi}))'
                ws.conditional_formatting.add(rng, FormulaRule(formula=[formula], fill=red_fill, stopIfTrue=False))

        for col_name, days_threshold in (days_until_highlight_columns or {}).items():
            if col_name in header:
                col_letter = ws.cell(row=1, column=header.index(col_name) + 1).column_letter
                rng = f"{col_letter}2:{col_letter}{last_row}"
                first = f"{col_letter}2"
                # ISNUMBER guards against text placeholders (e.g. "Pending
                # for yarn" when the delivery date can't be computed yet)
                # -- those aren't a real date, so they must never be
                # subtracted from TODAY() or Excel shows a #VALUE! error.
                formula = f'AND(ISNUMBER({first}),({first}-TODAY())<{days_threshold})'
                ws.conditional_formatting.add(rng, FormulaRule(formula=[formula], fill=red_fill, stopIfTrue=False))

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = ws.dimensions
    for col in ws.columns:
        letter = col[0].column_letter
        content_width = max((len(_clean(c.value)) for c in col), default=8)
        ws.column_dimensions[letter].width = max(10, content_width + 2)


# Old private name, kept so existing imports keep working.
_style_sheet = style_sheet
