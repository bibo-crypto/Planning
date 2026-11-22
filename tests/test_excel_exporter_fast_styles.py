"""excel_exporter.write_data registers each distinct style once instead of once per cell (about 5 s of a 600-row export).
The cells must look exactly as before: every cell of a workbook written the old per-cell way and the new way is compared."""
import dataclasses
import io
import random
import time
from datetime import datetime
from typing import Sequence

import openpyxl
from openpyxl.styles import Alignment

from exporters import excel_exporter as exporter
from exporters.excel_exporter import (
    BODY_FONT, CELL_BORDER, GENERAL_FORMAT, INTEGER_FORMAT, NUMBER_FORMAT, ROW_HEIGHT_WRAPPED, TEXT_FORMAT,
    _as_float, _as_integer,
)
from parsers.pdf_parser import OrderRow

COLUMNS = [("A", "pod_no", "text"), ("B", "article_description", "text"), ("C", "pos", "integer"),
           ("D", "unit_price", "number"), ("E", "po_date", "date"), ("F", "order_qty", "general"), ("G", "pod_no", "other")]


def _reference_write_data(
    ws: openpyxl.worksheet.worksheet.Worksheet,
    columns: list[tuple[str, str, str]],
    rows: Sequence[object],
) -> None:
    """Write all data rows with appropriate formatting. Standalone so any exporter can reuse it."""
    description_col_idx = next(
        (i + 1 for i, (_, attr, _) in enumerate(columns) if attr == "article_description"),
        None,
    )

    for row_idx, order_row in enumerate(rows, start=2):
        for col_idx, (_, attr, dtype) in enumerate(columns, start=1):
            raw_value = getattr(order_row, attr, "")
            cell = ws.cell(row=row_idx, column=col_idx)

            cell.font = BODY_FONT
            cell.border = CELL_BORDER

            if dtype == "text":
                cell.value = str(raw_value) if raw_value not in (None, "") else None
                cell.number_format = TEXT_FORMAT
                if col_idx == description_col_idx:
                    cell.alignment = Alignment(
                        horizontal="left", vertical="top", wrap_text=True
                    )
                else:
                    cell.alignment = Alignment(
                        horizontal="left", vertical="center"
                    )

            elif dtype == "integer":
                # Excel integer columns may receive values parsed from
                # PDF/Excel text, including a decimal-looking string.
                cell.value = _as_integer(raw_value)
                cell.number_format = INTEGER_FORMAT
                cell.alignment = Alignment(
                    horizontal="center", vertical="center"
                )

            elif dtype == "number":
                cell.value = _as_float(raw_value)
                cell.number_format = NUMBER_FORMAT
                cell.alignment = Alignment(
                    horizontal="right", vertical="center"
                )

            elif dtype == "general":
                cell.value = _as_float(raw_value)
                cell.number_format = GENERAL_FORMAT
                cell.alignment = Alignment(
                    horizontal="right", vertical="center"
                )

            elif dtype == "date":
                if isinstance(raw_value, datetime):
                    # A real date we generated ourselves (e.g. Ordini
                    # ELVY's CONSEGNA) — write as an actual Excel date.
                    cell.value = raw_value
                    cell.number_format = "DD/MM/YYYY"
                else:
                    # Store as text; Excel will display as-is (dates
                    # from PDFs vary too much to parse reliably)
                    cell.value = str(raw_value) if raw_value not in (None, "") else ""
                    cell.number_format = TEXT_FORMAT
                cell.alignment = Alignment(
                    horizontal="center", vertical="center"
                )

        # Taller rows for wrapped description text
        if description_col_idx:
            desc_val = getattr(order_row, "article_description", "")
            if desc_val and "\n" in str(desc_val):
                ws.row_dimensions[row_idx].height = ROW_HEIGHT_WRAPPED


def _rows(count=120):
    rng = random.Random(2)
    rows = []
    for i in range(count):
        kwargs = {}
        for field in dataclasses.fields(OrderRow):
            kind = str(field.type)
            if "int" in kind:
                kwargs[field.name] = rng.choice([rng.randint(1, 500), "12.0", "", None])
            elif "float" in kind:
                kwargs[field.name] = rng.choice([round(rng.random() * 100, 2), "3,5", "x", None])
            elif "str" in kind:
                kwargs[field.name] = rng.choice([f"{field.name[:6]}{i}", "", "two\nlines"])
        rows.append(OrderRow(**kwargs))
    rows[3].po_date = datetime(2026, 5, 4)          # a real date: written as a date, the others as text
    return rows


def _signature(cell):
    return (cell.value, cell.font.name, cell.font.sz, cell.font.b, cell.border.left.style, cell.border.left.color.rgb,
            cell.alignment.horizontal, cell.alignment.vertical, bool(cell.alignment.wrap_text), cell.number_format)


def _reloaded(write_data, rows):
    wb = openpyxl.Workbook()
    ws = wb.active
    exporter.write_header(ws, COLUMNS)
    write_data(ws, COLUMNS, rows)
    buffer = io.BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return openpyxl.load_workbook(buffer).active


def test_every_cell_looks_as_it_did_with_the_per_cell_styling():
    rows = _rows()
    new, old = _reloaded(exporter.write_data, rows), _reloaded(_reference_write_data, rows)
    assert (new.max_row, new.max_column) == (old.max_row, old.max_column) == (len(rows) + 1, len(COLUMNS))
    for new_row, old_row in zip(new.iter_rows(), old.iter_rows()):
        for a, b in zip(new_row, old_row):
            assert _signature(a) == _signature(b), a.coordinate
    assert {new.row_dimensions[r].height for r in range(2, len(rows) + 2)} == {old.row_dimensions[r].height for r in range(2, len(rows) + 2)}


def test_the_styles_used_are_the_documented_ones():
    ws = _reloaded(exporter.write_data, _rows(10))
    assert ws["A2"].number_format == TEXT_FORMAT and ws["A2"].alignment.horizontal == "left"
    assert ws["B2"].alignment.wrap_text is True and ws["B2"].alignment.vertical == "top"
    assert ws["C2"].number_format == INTEGER_FORMAT and ws["C2"].alignment.horizontal == "center"
    assert ws["D2"].number_format == NUMBER_FORMAT and ws["D2"].alignment.horizontal == "right"
    assert ws["F2"].number_format == GENERAL_FORMAT
    assert ws["E5"].number_format == "DD/MM/YYYY"                  # the real date of row 4
    assert ws["A2"].font.name == BODY_FONT.name and ws["A2"].border.left.style == CELL_BORDER.left.style


def test_writing_many_rows_is_fast():
    wb = openpyxl.Workbook()
    started = time.perf_counter()
    exporter.write_data(wb.active, COLUMNS, _rows(600))
    assert time.perf_counter() - started < 2.0, "600 rows took far longer than expected (about 4 s with per-cell styling)"
