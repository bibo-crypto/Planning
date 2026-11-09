"""Workbooks the program writes must open in Excel without the "We found a problem ... recover?" prompt.

Excel refuses an empty text cell (openpyxl writes "" as <c t="inlineStr"></c>), a numeric cell
without a number (NaN / inf) and over-long text; a comment starting with "=" turns into a formula
nobody wrote; and a date that arrives as text (with a time, as a date() or as NaN from pandas)
must still end up a real date or an empty cell.  utility/excel_values.py + safe_save_workbook.
"""
import dataclasses
import datetime as dt
import zipfile

import numpy as np
import openpyxl
import pandas as pd
import pytest

from exporters.master_formats import ERP_HEADERS
from pipelines.ordine_med import _to_date_value, export_erp_order_workbook
from pipelines.ordini_elvy import OrdiniElvyRow, RawYarnMatch, export_filato_full, export_ordini_full
from tests.test_first_bagno_elvy_kamal import _med_record
from utility import excel_io
from utility.excel_values import describe_invalid_cells, sanitize_workbook, to_excel_date

D = dt.datetime


# ---------------------------------------------------------------------------------------- dates
@pytest.mark.parametrize("value, expected", [
    (D(2026, 10, 20, 15, 30), D(2026, 10, 20)),
    (dt.date(2026, 10, 20), D(2026, 10, 20)),
    (pd.Timestamp("2026-10-20 08:00"), D(2026, 10, 20)),
    (np.datetime64("2026-10-20"), D(2026, 10, 20)),
    ("20/10/2026", D(2026, 10, 20)),
    ("20/10/26", D(2026, 10, 20)),
    ("20-10-2026", D(2026, 10, 20)),
    ("20.10.2026", D(2026, 10, 20)),
    ("2026-10-20", D(2026, 10, 20)),
    ("2026-10-20 00:00:00", D(2026, 10, 20)),           # how a pandas date looks once it became text
    ("2026-10-20T08:15:00", D(2026, 10, 20)),
    ("20/10/2026 10:30", D(2026, 10, 20)),
    ("20 Oct 2026", D(2026, 10, 20)),
    ("Oct 20, 2026", D(2026, 10, 20)),
    ("  20/10/2026  ", D(2026, 10, 20)),
    (46315, D(2026, 10, 20)),
    (46315.0, D(2026, 10, 20)),
    ("46315", D(2026, 10, 20)),
    ("46315.0", D(2026, 10, 20)),
])
def test_every_shape_a_date_arrives_in_becomes_a_real_date(value, expected):
    assert to_excel_date(value) == expected


@pytest.mark.parametrize("blank", [None, "", "   ", float("nan"), pd.NaT, np.datetime64("NaT"), np.nan, "nan", "NaT", "None"])
def test_blank_nan_and_nat_are_an_empty_cell(blank):
    assert to_excel_date(blank) is None


@pytest.mark.parametrize("value", ["soon", "week 42", 5, True, 1e9, float("inf"), "12/13/2026 xx"])
def test_anything_that_is_not_a_date_is_returned_unchanged(value):
    assert to_excel_date(value) is value or to_excel_date(value) == value


def test_ordine_med_uses_the_shared_converter():
    assert _to_date_value("2026-10-20 00:00:00") == D(2026, 10, 20)
    assert _to_date_value(float("nan")) is None and _to_date_value("") is None and _to_date_value("soon") == "soon"


# ----------------------------------------------------------------------------- the save step
def _dirty_workbook():
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["text", "", float("nan"), float("inf"), -float("inf"), pd.NaT, "x" * 40000, "=1+1", 5, 2.5, None])
    return wb


def test_sanitize_workbook_removes_what_excel_refuses_and_keeps_the_rest():
    wb = _dirty_workbook()
    assert sanitize_workbook(wb) == 5
    ws = wb.active
    assert [ws.cell(1, c).value for c in (1, 2, 3, 4, 5, 6)] == ["text", None, None, None, None, None]
    assert len(ws["G1"].value) == 32767                                  # openpyxl cuts at Excel's limit
    assert ws["H1"].value == "=1+1" and ws["H1"].data_type == "f"        # a real formula is not touched
    assert [ws["I1"].value, ws["J1"].value] == [5, 2.5]
    assert sanitize_workbook(wb) == 0


def test_safe_save_writes_a_workbook_excel_accepts(tmp_path):
    target = tmp_path / "out.xlsx"
    excel_io.safe_save_workbook(_dirty_workbook(), target)
    assert describe_invalid_cells(target) is None
    ws = openpyxl.load_workbook(target).active
    assert ws["A1"].value == "text" and ws["B1"].value is None and ws["C1"].value is None


def test_the_unsanitised_workbook_really_is_what_the_check_catches(tmp_path):
    """Guards the guard: the three defects are present in a plain openpyxl save and are all detected."""
    for value, wanted in [("", "text cell with no text"), (float("nan"), "numeric cell"), (float("inf"), "numeric cell")]:
        wb = openpyxl.Workbook()
        wb.active["A1"] = value
        path = tmp_path / "raw.xlsx"
        wb.save(path)
        assert wanted in (describe_invalid_cells(path) or "")


def test_a_broken_workbook_never_replaces_a_good_file(tmp_path, monkeypatch):
    target = tmp_path / "ok.xlsx"
    good = openpyxl.Workbook()
    good.active["A1"] = "good"
    excel_io.safe_save_workbook(good, target)
    monkeypatch.setattr(excel_io, "sanitize_workbook", lambda workbook: 0)      # pretend the cleaning failed
    bad = openpyxl.Workbook()
    bad.active["A1"] = float("nan")
    with pytest.raises(RuntimeError, match="would not open cleanly"):
        excel_io.safe_save_workbook(bad, target)
    assert openpyxl.load_workbook(target).active["A1"].value == "good"          # the old file is untouched
    assert not list(tmp_path.glob(".*.tmp"))                                     # and no temp file is left behind


def test_formula_cells_are_not_mistaken_for_broken_numbers(tmp_path):
    wb = openpyxl.Workbook()
    wb.active["A1"] = "=SUM(1,2)"
    wb.active["B1"] = 7
    target = tmp_path / "f.xlsx"
    excel_io.safe_save_workbook(wb, target)
    assert describe_invalid_cells(target) is None


# -------------------------------------------------------------------- the three system-file writers
def _clean(path):
    assert describe_invalid_cells(path) is None
    assert not any(b"inlineStr\"></c>" in zipfile.ZipFile(path).read(n) for n in zipfile.ZipFile(path).namelist() if n.endswith(".xml"))


def _cell(ws, header, row=2):
    return ws.cell(row, [c.value for c in ws[1]].index(header) + 1)


ELVY = dict(cliente=3009, articolo_delta="C011220S", coloredfm=31264, quantity_cones=672, data_consegna=D(2026, 11, 24),
            commento="PG-X-PO-1500-2026", data_riconsegna=D(2026, 11, 23), sigla_dispo="D", bagno_proposto="T1200", macchina=3306)


@pytest.mark.parametrize("patch, check", [
    (dict(commento="=PG-X(8)-PM"), lambda ws: (_cell(ws, "COMMENTO").value, _cell(ws, "COMMENTO").data_type) == ("=PG-X(8)-PM", "s")),
    (dict(bagno_proposto=""), lambda ws: _cell(ws, "BAGNO PREPOSTO").value is None),
    (dict(data_consegna=dt.date(2026, 11, 24)), lambda ws: _cell(ws, "CONSEGNA").value == D(2026, 11, 24)),
    (dict(data_consegna="2026-11-24 00:00:00"), lambda ws: _cell(ws, "CONSEGNA").value == D(2026, 11, 24)),
    (dict(data_riconsegna=pd.NaT), lambda ws: _cell(ws, "DATA RICONSEGNA").value is None),
    (dict(data_consegna=float("nan")), lambda ws: _cell(ws, "CONSEGNA").value is None),
])
def test_elvy_and_kamal_erp_file_survives_awkward_values(tmp_path, patch, check):
    target = tmp_path / "erp.xlsx"
    export_ordini_full(target, [OrdiniElvyRow(**{**ELVY, **patch})])
    _clean(target)
    assert check(openpyxl.load_workbook(target)["Foglio1"])


@pytest.mark.parametrize("patch, check", [
    (dict(commento="=PG-X(8)-PM"), lambda ws: (_cell(ws, "COMMENTO").value, _cell(ws, "COMMENTO").data_type) == ("=PG-X(8)-PM", "s")),
    (dict(bagno_prepostato=""), lambda ws: _cell(ws, "BAGNO PREPOSTO").value is None),
    (dict(consegna=float("nan")), lambda ws: _cell(ws, "CONSEGNA").value is None),
    (dict(consegna=pd.NaT), lambda ws: _cell(ws, "CONSEGNA").value is None),
    (dict(consegna="2026-10-20 00:00:00"), lambda ws: _cell(ws, "CONSEGNA").value == D(2026, 10, 20)),
    (dict(data_riconsegna="20/10/2026 10:30"), lambda ws: _cell(ws, "DATA RICONSEGNA").value == D(2026, 10, 20)),
    (dict(data_riconsegna=float("nan")), lambda ws: _cell(ws, "DATA RICONSEGNA").value is None),
])
def test_ordine_med_erp_file_survives_awkward_values(tmp_path, patch, check):
    target = tmp_path / "erp.xlsx"
    export_erp_order_workbook(target, [dataclasses.replace(_med_record(), **patch)])
    _clean(target)
    assert check(openpyxl.load_workbook(target)["Foglio1"])
    assert tuple(c.value for c in openpyxl.load_workbook(target)["Foglio1"][1]) == ERP_HEADERS


@pytest.mark.parametrize("match, check", [
    (RawYarnMatch("G1", "", "159806", 10, 5.0), lambda ws: ws["B2"].value is None),                       # no titolo
    (RawYarnMatch("G1", "=1+1", "159806", 10, 5.0), lambda ws: (ws["B2"].value, ws["B2"].data_type) == ("=1+1", "s")),
    (RawYarnMatch("G1", "t", "159806", 10, float("nan")), lambda ws: ws["E2"].value is None),             # no weight
    (RawYarnMatch("G1", "t", "159806", float("nan"), 5.0), lambda ws: ws["D2"].value is None),
    (RawYarnMatch("G1", "t", None, 10, 5.0), lambda ws: ws["C2"].value is None),
    (RawYarnMatch("G1", "t", "159806", np.float64(10), np.float64(5.5)), lambda ws: (ws["D2"].value, ws["E2"].value) == (10, 5.5)),
])
def test_filato_file_survives_awkward_values(tmp_path, match, check):
    target = tmp_path / "filato.xlsx"
    export_filato_full(target, [match])
    _clean(target)
    assert check(openpyxl.load_workbook(target)["Filato x Tinturia"])
