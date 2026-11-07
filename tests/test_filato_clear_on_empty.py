from types import SimpleNamespace
from unittest.mock import Mock

import openpyxl

from exporters import master_formats
from gui.tabs import shared_order_actions
from pipelines import create_conversion
from pipelines.ordini_elvy import RawYarnMatch, export_filato_full


def _old_filato_row():
    return [RawYarnMatch("G130348S", "140/2", "159806", 192, 176.0)]


def test_biglietti_conversion_clears_filato_when_raw_rows_are_missing(tmp_path, monkeypatch):
    filato_path = tmp_path / create_conversion.FILATO_FILE_NAME.format(customer="ELVY")
    export_filato_full(filato_path, _old_filato_row())

    monkeypatch.setattr(create_conversion, "_enrich", lambda *args: None)
    monkeypatch.setattr(create_conversion, "build_output_stem", lambda *args: "order")
    monkeypatch.setattr(create_conversion, "export_workbook", lambda *args, **kwargs: None)
    monkeypatch.setattr(create_conversion, "append_create_excel", lambda *args, **kwargs: None)
    monkeypatch.setattr(create_conversion, "_split_pg_x", lambda records: ([], []))
    monkeypatch.setattr(create_conversion, "_filato_rows", lambda *args: [])

    request = create_conversion.ConversionRequest(
        kind="elvy",
        data_path=tmp_path / "order.xlsx",
        dispo_path=None,
        template=tmp_path / "template.docx",
        output_dir=tmp_path,
        filato_dir=tmp_path,
    )
    result = create_conversion._convert_shared_customer(
        request, [], [], create_conversion.CommonSources()
    )

    assert result.filato_file == filato_path
    workbook = openpyxl.load_workbook(filato_path)
    try:
        ws = workbook["Filato x Tinturia"]
        assert ws.max_row == 1
        assert tuple(cell.value for cell in ws[1]) == master_formats.FILATO_HEADERS
    finally:
        workbook.close()


def test_printing_only_unassigned_biglietti_clears_shared_filato(tmp_path, monkeypatch):
    filato_path = tmp_path / "Filato X Tinturia.xlsx"
    export_filato_full(filato_path, _old_filato_row())

    monkeypatch.setattr(shared_order_actions, "export_word", lambda *args, **kwargs: None)
    monkeypatch.setattr(shared_order_actions, "post_to_ui", lambda *args, **kwargs: None)
    page = SimpleNamespace(
        shared_excel_path=tmp_path / "Create Orders.xlsx",
        template_path=tmp_path / "template.docx",
        _logger=Mock(),
        _set_status=Mock(),
        _load_common_sources=Mock(side_effect=AssertionError("no raw rows need source data")),
    )
    record = SimpleNamespace(customer_code="3009", raw_batch="")

    shared_order_actions.SharedOrdersActionsMixin._worker_shared_biglietti(
        page, [record], tmp_path / "Biglietti_Stampati.docx", []
    )

    workbook = openpyxl.load_workbook(filato_path)
    try:
        ws = workbook["Filato x Tinturia"]
        assert ws.max_row == 1
        assert tuple(cell.value for cell in ws[1]) == master_formats.FILATO_HEADERS
    finally:
        workbook.close()
