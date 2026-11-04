"""Prezzi Ordine Med numbering and the pre-convert input check."""
import openpyxl
import pytest

from exporters import input_check
from pipelines.ordine_med import next_prezzi_path


def test_prezzi_ordine_med_gets_the_next_number(tmp_path):
    assert next_prezzi_path(tmp_path).name == "Prezzi Ordine Med 1.xlsx"
    (tmp_path / "Prezzi Ordine Med 1.xlsx").touch(); (tmp_path / "Prezzi Ordine Med 4.xlsx").touch()
    assert next_prezzi_path(tmp_path).name == "Prezzi Ordine Med 5.xlsx"


def _book(path, sheet, headers):
    wb = openpyxl.Workbook(); ws = wb.active; ws.title = sheet
    ws.append(headers); ws.append(["x"] * len(headers)); wb.save(path)


def test_input_check_names_missing_columns(tmp_path):
    full = tmp_path / "med.xlsx"
    _book(full, "ORDINE", list(input_check.MED_ORDER_COLUMNS))
    assert input_check.check_med_input(full) == []
    partial = tmp_path / "med2.xlsx"
    _book(partial, "ORDINE", ["ARTICOLO", "COLORE", "ROCC", "ABBIN", "CONSEGNA", "PT GRG"])
    (problem,) = input_check.check_med_input(partial)
    assert "TITOLO" in problem and "DESCR COL" in problem


def test_input_check_for_biglietti_order_file(tmp_path):
    path = tmp_path / "erp.xlsx"
    _book(path, "Sheet1", ["Cliente", "Articolo", "Colore", "Ordine", "Riga", "Partita", "Ordinata", "Consegna"])
    problems = input_check.check_order_file("elvy", path)
    assert any("Descrizione aggiuntiva ordine" in p for p in problems)
    assert any("Dispo-Bagno" in p for p in problems)
    assert input_check.check_order_file("elvy", tmp_path / "missing.xlsx") == []   # unreadable: left to the loader
