"""style_sheet writes the cell styles straight into the style arrays (fast); the file it produces must be exactly the one the
plain openpyxl descriptors (``cell.alignment = ...``) produce -- the old, ~45 times slower way."""
import io
import time
import zipfile
from datetime import date

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side

from exporters.biglietti.workbook_io import style_sheet


def _reference_style_sheet(ws):
    """The part of style_sheet that was optimised, written the slow, obviously-correct way."""
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


def _workbook(rows=300):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["Partita Col", "Bagno", "Delivery Date", "Commento"])
    for i in range(1, rows):
        ws.append([str(i), f"B{i % 3}", date(2026, 12, 1), "x" * (i % 7)])
    ws["D5"].font = Font(bold=True, color="FF0000")          # styles that were there before must survive
    ws["B9"].number_format = "0.00"
    ws["A12"].fill = PatternFill("solid", fgColor="FFFF00")
    ws["B30"].alignment = Alignment(horizontal="right")
    return wb, ws


def _saved_parts(wb):
    buffer = io.BytesIO()
    wb.save(buffer)
    archive = zipfile.ZipFile(buffer)
    return archive.read("xl/styles.xml"), archive.read("xl/worksheets/sheet1.xml")


def _signature(cell):
    """Everything about a cell's style as plain values (the openpyxl proxies themselves do not compare reliably)."""
    return (
        cell.alignment.horizontal, cell.alignment.vertical, bool(cell.alignment.wrap_text),
        cell.border.left.style, cell.border.right.style, cell.border.top.style, cell.border.bottom.style,
        cell.border.left.color.rgb if cell.border.left.color else None,
        cell.fill.fill_type, cell.fill.fgColor.rgb,
        cell.font.b, cell.font.color.rgb if cell.font.color else None,
        cell.number_format,
    )


def test_the_fast_style_sheet_gives_every_body_cell_the_style_the_plain_openpyxl_way_gives():
    fast_wb, fast_ws = _workbook()
    style_sheet(fast_ws)
    slow_wb, slow_ws = _workbook()
    _reference_style_sheet(slow_ws)
    for fast_row, slow_row in zip(fast_ws.iter_rows(min_row=2), slow_ws.iter_rows(min_row=2)):
        for fast, slow in zip(fast_row, slow_row):
            assert _signature(fast) == _signature(slow), fast.coordinate
    # what was there before the call survives, what the call sets is replaced -- as before
    assert fast_ws["D5"].font.b is True and fast_ws["D5"].font.color.rgb == "00FF0000"
    assert fast_ws["B9"].number_format == "0.00"
    assert fast_ws["B30"].alignment.horizontal == "center"
    assert fast_ws["A1"].alignment.wrap_text is True and not fast_ws["A2"].alignment.wrap_text
    assert fast_ws["A2"].fill.fgColor.rgb == "FFDCE6F1" and fast_ws["A3"].fill.fill_type is None   # even rows only are banded
    assert _saved_parts(fast_wb)                                                                    # and the file can be written


def test_the_fast_style_sheet_writes_a_workbook_that_reloads_with_the_same_styles():
    wb, ws = _workbook()
    style_sheet(ws, date_columns=("Delivery Date",))
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    again = openpyxl.load_workbook(buffer).active
    for before, after in zip(ws.iter_rows(), again.iter_rows()):
        for a, b in zip(before, after):
            assert _signature(a) == _signature(b), a.coordinate
    assert again["C2"].number_format == "dd/mm/yyyy"


def test_style_sheet_does_not_depend_on_the_number_of_rows_the_slow_way_did():
    wb, ws = _workbook(rows=1500)
    started = time.perf_counter()
    style_sheet(ws, date_columns=("Delivery Date",))
    assert time.perf_counter() - started < 3.0, "styling 1500 rows took far longer than expected (it was ~9 s before)"
