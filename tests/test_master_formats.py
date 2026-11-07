"""The separate "system" files follow the master workbooks (exporters/master_formats.py).

* ERP file (ELVY / EL KAMAL writer and MED writer): header, fonts, borders, widths, a real
  number / date / text type per column, the Excel table and the duplicate highlighting.
* Filato x Tinturia file: the master's headers, the Excel table and the four empty
  "complete from another raw yarn" columns.
Only the format is new -- the values the writers produce are asserted elsewhere.
"""
import datetime as dt
from zipfile import ZipFile
from xml.etree import ElementTree as ET

import openpyxl
import pytest
from openpyxl.styles.numbers import is_date_format

from exporters import master_formats as mf
from pipelines.ordini_elvy import OrdiniElvyRow, RawYarnMatch, export_filato_full, export_ordini_full, read_filato_tinturia_sheet
from tests.test_first_bagno_elvy_kamal import _med_record


def _elvy_rows(count):
    return [OrdiniElvyRow(cliente=3009, articolo_delta=f"C01122{i}S", coloredfm=31264 + i, quantity_cones=672 + i,
                          data_consegna=dt.datetime(2026, 11, 24), commento="PG-X-PO-1500-2026",
                          data_riconsegna=dt.datetime(2026, 11, 23), sigla_dispo="D", bagno_proposto=f"T120{i}",
                          macchina=3309) for i in range(count)]


def _write_elvy(path, count):
    export_ordini_full(path, _elvy_rows(count))
    return openpyxl.load_workbook(path)[mf.ERP_SHEET_NAME]


def _write_med(path, count):
    from pipelines.ordine_med import export_erp_order_workbook
    export_erp_order_workbook(path, [_med_record(bagno_prepostato="") for _ in range(count)])
    return openpyxl.load_workbook(path)[mf.ERP_SHEET_NAME]


def test_med_erp_export_does_not_keep_unused_biglietti_styles(tmp_path):
    from pipelines.ordine_med import export_erp_order_workbook

    path = tmp_path / "erp.xlsx"
    export_erp_order_workbook(path, [_med_record(bagno_prepostato="")])
    workbook = openpyxl.load_workbook(path)
    try:
        legacy_biglietti_fill = "FF1F4E78"
        assert all(fill.fgColor.rgb != legacy_biglietti_fill for fill in workbook._fills)
        assert all(font.color is None or font.color.rgb != "00FFFFFF" for font in workbook._fonts)
    finally:
        workbook.close()


WRITERS = {"ELVY/KAMAL": _write_elvy, "MED": _write_med}


def _border(cell):
    b = cell.border
    return tuple(side.style for side in (b.left, b.right, b.top, b.bottom))


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_erp_file_has_the_master_layout_and_column_types(tmp_path, writer):
    ws = WRITERS[writer](tmp_path / "erp.xlsx", 3)
    assert ws.title == mf.ERP_SHEET_NAME
    assert tuple(c.value for c in ws[1]) == mf.ERP_HEADERS
    for index, width in enumerate(mf.ERP_WIDTHS, start=1):
        assert ws.column_dimensions[openpyxl.utils.get_column_letter(index)].width == pytest.approx(width)
    assert ws.freeze_panes is None and ws.auto_filter.ref is None

    head = ws["A1"]
    assert (head.font.name, head.font.sz, head.fill.fill_type) == ("Calibri", 10, "solid")
    assert (head.alignment.horizontal, head.alignment.vertical) == ("center", "center")
    assert _border(ws["A1"]) == (None, "thin", None, "thin") and _border(ws["M1"]) == ("thin", None, None, "thin")

    for row in (2, 3, 4):
        for column, header in enumerate(mf.ERP_HEADERS, start=1):
            cell = ws.cell(row, column)
            assert (cell.font.name, cell.font.sz, cell.fill.fill_type) == ("Aptos Narrow", 11, None), (row, header)
            assert (cell.alignment.horizontal, cell.alignment.vertical) == ("center", "center")
            assert _border(cell) == ("thin",) * 4
            if header in mf.ERP_DATE_HEADERS:
                assert isinstance(cell.value, dt.datetime), header                       # a real date ...
                assert cell.number_format == mf.DATE_FORMAT and is_date_format(cell.number_format)   # ... shown as one
            else:
                assert cell.number_format == "General", header
    for name in ("CLIENTE", "COLORE", "Q.TA", "LAVORANTE", "LAV. SUCC", "MAG. GREGGIO", "GRUPPO MACCHINA"):
        assert isinstance(ws.cell(2, mf.ERP_HEADERS.index(name) + 1).value, int), name   # numbers stay numbers
    for name in ("ARTICOLO", "COMMENTO", "SIGLA DISPOSIZIONE"):
        assert isinstance(ws.cell(2, mf.ERP_HEADERS.index(name) + 1).value, str), name


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_erp_file_encodes_blank_text_cells_as_valid_blank_cells(tmp_path, writer):
    path = tmp_path / "erp.xlsx"
    WRITERS[writer](path, 1)

    with ZipFile(path) as archive:
        root = ET.fromstring(archive.read("xl/worksheets/sheet1.xml"))
    ns = {"main": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    empty_inline_strings = [
        cell.get("r")
        for cell in root.findall(".//main:c[@t='inlineStr']", ns)
        if cell.find("main:is", ns) is None
    ]
    assert empty_inline_strings == []


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_erp_file_is_an_excel_table_with_duplicate_highlighting(tmp_path, writer):
    ws = WRITERS[writer](tmp_path / "erp.xlsx", 4)
    (table,) = ws.tables.values()
    assert (table.name, table.ref, table.tableStyleInfo.name) == ("Table1", "A1:M5", "TableStyleMedium2")
    assert [c.name for c in table.tableColumns] == list(mf.ERP_HEADERS)
    rules = {str(group.sqref): [(r.type, r.dxf.font.color.rgb, r.dxf.fill.bgColor.rgb) for r in group.rules]
             for group in ws.conditional_formatting}
    assert rules == {"C2:C5": [("duplicateValues", "FF006100", "FFC6EFCE")],     # COLORE twice: green
                     "L2:L5": [("duplicateValues", "FF9C0006", "FFFFC7CE")]}     # BAGNO PREPOSTO twice: red


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_an_existing_erp_file_is_cleared_and_rebuilt_in_the_master_format(tmp_path, writer):
    target = tmp_path / "erp.xlsx"
    # a previous, differently formatted file with an older, longer order in it
    old = openpyxl.Workbook()
    old.active.append(list(mf.ERP_HEADERS))
    for i in range(6):
        old.active.append([9999 + i] * 13)
    old.active.auto_filter.ref = "A1:M7"
    old.active.freeze_panes = "A2"
    old.save(target)

    ws = WRITERS[writer](target, 2)
    assert ws.max_row == 3                                           # only the new order's two rows
    assert all(ws.cell(r, 1).value != 9999 for r in (2, 3))
    (table,) = ws.tables.values()
    assert table.ref == "A1:M3"                                      # the table shrank with the data
    assert ws.freeze_panes is None and ws.auto_filter.ref is None
    assert ws["A2"].font.name == "Aptos Narrow" and ws["A1"].fill.fill_type == "solid"


@pytest.mark.parametrize("writer", sorted(WRITERS))
def test_an_erp_file_without_rows_is_just_the_styled_header(tmp_path, writer):
    ws = WRITERS[writer](tmp_path / "erp.xlsx", 0)
    assert ws.max_row == 1 and not ws.tables and len(ws.conditional_formatting) == 0
    assert ws["A1"].fill.fill_type == "solid" and tuple(c.value for c in ws[1]) == mf.ERP_HEADERS


def test_an_unexpected_erp_layout_is_left_untouched():
    ws = openpyxl.Workbook().active
    ws.append(["not", "the", "erp", "headers"])
    ws.append([1, 2, 3, 4])
    assert mf.apply_erp_master_format(ws) is False
    assert ws["A1"].font.name == "Calibri" and ws["A1"].fill.fill_type is None and not ws.tables


# ----------------------------------------------------------------------------------- Filato x Tinturia
MASTER_ROWS = [
    RawYarnMatch("G130348S", "140/2", "159806", 192, 176.0),
    RawYarnMatch("G130365S", "170/2", "159805", 182, 172.3),
    RawYarnMatch("G130036S", "30/1 LINO", "AB-12", 38, 34.45),
]


def test_filato_file_has_the_master_layout(tmp_path):
    target = tmp_path / "Filato x Tinturia.xlsx"
    assert export_filato_full(target, MASTER_ROWS) == 3
    ws = openpyxl.load_workbook(target)["Filato x Tinturia"]
    assert tuple(c.value for c in ws[1]) == mf.FILATO_HEADERS
    assert mf.FILATO_HEADERS[6:] == ("تكمله من خام", "عدد.", "تكمله من خام..", "عدد..")
    for index, width in enumerate(mf.FILATO_WIDTHS, start=1):
        assert ws.column_dimensions[openpyxl.utils.get_column_letter(index)].width == pytest.approx(width)
    row = [c.value for c in ws[2]]
    assert row == ["G130348S", "140/2", 159806, 192, 176.0, "تحضير خام", None, None, None, None]
    assert isinstance(ws["C2"].value, int) and ws["C4"].value == "AB-12"          # Partita.GG: a number, unless it is not one
    assert ws["B2"].number_format == "@" and ws["C2"].number_format == "General"
    assert ws["F2"].font.b and not ws["A2"].font.b                                   # Custom is bold, like the master
    for column in range(1, 11):                                                      # the empty completion columns are styled too
        cell = ws.cell(2, column)
        assert (cell.font.name, cell.font.sz) == ("Calibri", 11) and cell.alignment.horizontal == "center"
        assert _border(cell) == ("thin",) * 4


def test_filato_file_is_an_excel_table_with_duplicate_partita_highlighting(tmp_path):
    target = tmp_path / "filato.xlsx"
    export_filato_full(target, MASTER_ROWS)
    ws = openpyxl.load_workbook(target)["Filato x Tinturia"]
    (table,) = ws.tables.values()
    assert (table.name, table.ref, table.tableStyleInfo.name) == ("تحضير_خيط_خام", "A1:J4", "TableStyleMedium7")
    assert [c.name for c in table.tableColumns] == list(mf.FILATO_HEADERS)
    assert ws.freeze_panes is None and ws.auto_filter.ref is None
    rules = {str(g.sqref): [(r.type, r.dxf.font.color.rgb) for r in g.rules] for g in ws.conditional_formatting}
    assert rules == {"C2:C4": [("duplicateValues", "FF9C0006")]}


def test_filato_file_reads_back_with_the_masters_own_headers(tmp_path):
    target = tmp_path / "filato.xlsx"
    export_filato_full(target, MASTER_ROWS)
    rows = read_filato_tinturia_sheet(target)
    assert [(r.articolo, r.titolo, r.partita, r.rocce, r.peso, r.label) for r in rows] == [
        ("G130348S", "140/2", "159806", 192.0, 176.0, "تحضير خام"),
        ("G130365S", "170/2", "159805", 182.0, 172.3, "تحضير خام"),
        ("G130036S", "30/1 LINO", "AB-12", 38.0, 34.45, "تحضير خام"),
    ]


def test_a_numeric_partita_cell_is_read_without_a_decimal_part(tmp_path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "Filato x Tinturia"
    ws.append(["Articolo", "Titolo", "Partita.GG", "عدد", "وزن", "Custom"])
    ws.append(["G130348S", "140/2", 159806.0, 192, 176, "تحضير خام"])
    wb.save(tmp_path / "f.xlsx")
    assert read_filato_tinturia_sheet(tmp_path / "f.xlsx")[0].partita == "159806"


def test_an_existing_filato_file_is_cleared_and_rebuilt_and_an_empty_one_is_header_only(tmp_path):
    target = tmp_path / "filato.xlsx"
    export_filato_full(target, MASTER_ROWS)
    export_filato_full(target, [RawYarnMatch("G999999S", "60/1", "222111", 5, 50.0)])
    ws = openpyxl.load_workbook(target)["Filato x Tinturia"]
    assert ws.max_row == 2 and ws["C2"].value == 222111 and next(iter(ws.tables.values())).ref == "A1:J2"
    export_filato_full(target, [])
    ws = openpyxl.load_workbook(target)["Filato x Tinturia"]
    assert ws.max_row == 1 and not ws.tables and tuple(c.value for c in ws[1]) == mf.FILATO_HEADERS
