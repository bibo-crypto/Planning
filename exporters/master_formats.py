"""The look of the two separate "system" files, taken from the master workbooks.

* ``EXCEL PER ORDINE VENDITA EGITTO`` -- the ERP import file written for ELVY, MED and
  EL KAMAL (master: EXCEL_PER_ORDINE_VENDITA_EGITTO.xlsx).
* ``Filato x Tinturia`` -- the raw-yarn file (master: Filato x Tinturia ... .xlsx), which also
  carries two "complete from another raw yarn" column pairs.

Only the *format* lives here -- header texts and widths, fonts, borders, the type of every
column (number / date / text), the Excel table and the duplicate highlighting.  What goes
into the cells is still decided by the writers, so no customer logic changes.  The files are
always rebuilt from scratch, so the format is the master's every time, whether the target file
existed or not.

The ERP sheet is always named ``Foglio1``, as required by the import master.
Dates are real Excel dates displayed as day/month/year for the ERP workflow.
"""
from __future__ import annotations

from typing import Iterable

from openpyxl.formatting.rule import Rule
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.styles.colors import Color
from openpyxl.styles.differential import DifferentialStyle
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

DATE_FORMAT = "dd/mm/yyyy"
GENERAL = "General"

_BLACK = Color(indexed=64)        # the master's border colour ("automatic")
_THIN = Side(style="thin", color=_BLACK)
_CENTER = Alignment(horizontal="center", vertical="center")

_GREEN = DifferentialStyle(font=Font(color="FF006100"), fill=PatternFill(bgColor="FFC6EFCE"))
_RED = DifferentialStyle(font=Font(color="FF9C0006"), fill=PatternFill(bgColor="FFFFC7CE"))


# --------------------------------------------------------------------------- ERP system file
ERP_HEADERS = (
    "CLIENTE", "ARTICOLO", "COLORE", "Q.TA", "CONSEGNA", "COMMENTO", "LAVORANTE", "LAV. SUCC",
    "DATA RICONSEGNA", "MAG. GREGGIO", "SIGLA DISPOSIZIONE", "BAGNO PREPOSTO", "GRUPPO MACCHINA",
)
ERP_WIDTHS = (
    11.7109375, 13.42578125, 11.85546875, 9.28515625, 14.42578125, 43.42578125, 15.140625,
    13.5703125, 20.7109375, 17.28515625, 21.28515625, 20.140625, 21.42578125,
)
ERP_DATE_HEADERS = ("CONSEGNA", "DATA RICONSEGNA")
ERP_SHEET_NAME = "Foglio1"
ERP_TABLE_NAME = "Table1"
ERP_TABLE_STYLE = "TableStyleMedium2"
ERP_HEADER_FONT = Font(name="Calibri", size=10, color=Color(theme=1))
ERP_HEADER_FILL = PatternFill("solid", fgColor=Color(theme=0, tint=-0.3499862666707358))   # white, 35% darker
ERP_BODY_FONT = Font(name="Aptos Narrow", size=11)


def _header_border(index: int, columns: int) -> Border:
    """Header cells: a thin line between neighbours and underneath, none on the outer top/left/right."""
    return Border(left=_THIN if index > 1 else Side(), right=_THIN if index < columns else Side(),
                  bottom=_THIN, top=Side())


def _header_row(ws, headers: tuple[str, ...]) -> list[str]:
    return [str(ws.cell(1, c).value or "").strip() for c in range(1, len(headers) + 1)]


def _add_table(ws, name: str, style: str, columns: int, last_row: int) -> None:
    table = Table(displayName=name, name=name, ref=f"A1:{get_column_letter(columns)}{last_row}")
    table.tableStyleInfo = TableStyleInfo(name=style, showFirstColumn=False, showLastColumn=False,
                                          showRowStripes=True, showColumnStripes=False)
    ws.add_table(table)


def _duplicates(ws, column_letter: str, last_row: int, style: DifferentialStyle) -> None:
    ws.conditional_formatting.add(f"{column_letter}2:{column_letter}{last_row}",
                                  Rule(type="duplicateValues", dxf=style))


def apply_erp_master_format(ws) -> bool:
    """Give an already filled ERP sheet (header in row 1, data from row 2) the master's format.

    Values are never touched. Renames the matching sheet to the master's required ``Foglio1``.
    Returns False, leaving the sheet as it was, when row 1 is not the 13 ERP headers (so an
    unexpected layout can never make a conversion fail).
    """
    if _header_row(ws, ERP_HEADERS) != list(ERP_HEADERS):
        return False
    ws.title = ERP_SHEET_NAME
    columns = len(ERP_HEADERS)
    last_row = ws.max_row

    ws.auto_filter.ref = None          # the Excel table carries its own filter
    ws.freeze_panes = None             # the master has none

    for index, header in enumerate(ERP_HEADERS, start=1):
        cell = ws.cell(1, index)
        cell.font, cell.fill, cell.alignment = ERP_HEADER_FONT, ERP_HEADER_FILL, _CENTER
        cell.border = _header_border(index, columns)
        number_format = DATE_FORMAT if header in ERP_DATE_HEADERS else GENERAL
        cell.number_format = number_format
        for row in range(2, last_row + 1):
            body = ws.cell(row, index)
            body.font, body.alignment, body.number_format = ERP_BODY_FONT, _CENTER, number_format
            body.fill = PatternFill()          # the master's data cells have no fill
            body.border = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
        ws.column_dimensions[get_column_letter(index)].width = ERP_WIDTHS[index - 1]

    if last_row >= 2:                  # an Excel table needs at least one data row
        _add_table(ws, ERP_TABLE_NAME, ERP_TABLE_STYLE, columns, last_row)
        _duplicates(ws, "C", last_row, _GREEN)    # COLORE: the same colour twice
        _duplicates(ws, "L", last_row, _RED)      # BAGNO PREPOSTO: the same bath twice
    return True


# --------------------------------------------------------------------- Filato x Tinturia file
FILATO_HEADERS = (
    "Articolo", "Titolo", "Partita.GG", "عدد", "وزن", "Custom",
    "تكمله من خام", "عدد.", "تكمله من خام..", "عدد..",
)
FILATO_WIDTHS = (
    12.5703125, 10.7109375, 14.85546875, 8.7109375, 9.0, 12.28515625,
    15.42578125, 9.28515625, 16.5703125, 9.85546875,
)
FILATO_TABLE_NAME = "تحضير_خيط_خام"
FILATO_TABLE_STYLE = "TableStyleMedium7"
_FILATO_BOLD_HEADERS = FILATO_HEADERS[4:]        # the master bolds وزن .. عدد..
_FILATO_BOLD_BODY = "Custom"
_FILATO_TEXT_HEADERS = ("Titolo",)               # the only column formatted as text ("@")
_FILATO_HEADER_FORMATS = {"Titolo": "@", "وزن": "0.00", "Custom": "0.00"}   # as carried by the master's header row
_BLACK_FONT_COLOR = Color(theme=1)


def partita_value(partita):
    """Partita.GG is a number in the master; a lot that is not purely digits stays text."""
    text = str(partita if partita is not None else "").strip()
    return int(text) if text.isdigit() else text


def write_filato_master_sheet(ws, matches: Iterable) -> int:
    """Fill *ws* (an empty sheet) with the Filato x Tinturia master: header, one row per
    RawYarnMatch, the four empty "complete from another raw yarn" columns, format and table.
    Returns the number of rows written."""
    ws.append(list(FILATO_HEADERS))
    count = 0
    for match in matches:
        ws.append([match.articolo, match.titolo, partita_value(match.partita), match.rocce, match.peso,
                   match.label, None, None, None, None])
        count += 1
    last_row = ws.max_row
    columns = len(FILATO_HEADERS)

    for index, header in enumerate(FILATO_HEADERS, start=1):
        head = ws.cell(1, index)
        head.font = Font(name="Calibri", size=11, bold=header in _FILATO_BOLD_HEADERS)
        head.alignment = _CENTER
        head.border = _header_border(index, columns)
        head.number_format = _FILATO_HEADER_FORMATS.get(header, GENERAL)
        for row in range(2, last_row + 1):
            body = ws.cell(row, index)
            body.font = Font(name="Calibri", size=11, bold=header == _FILATO_BOLD_BODY, color=_BLACK_FONT_COLOR)
            body.alignment = _CENTER
            body.border = Border(left=_THIN, right=_THIN, top=_THIN, bottom=_THIN)
            body.number_format = "@" if header in _FILATO_TEXT_HEADERS else GENERAL
        ws.column_dimensions[get_column_letter(index)].width = FILATO_WIDTHS[index - 1]

    if last_row >= 2:
        _add_table(ws, FILATO_TABLE_NAME, FILATO_TABLE_STYLE, columns, last_row)
        _duplicates(ws, "C", last_row, _RED)      # the same Partita.GG twice
    return count
