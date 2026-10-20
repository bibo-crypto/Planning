from pathlib import Path

import openpyxl

from exporters.biglietti_exporter import (
    OrderRecord,
    _kamal_kg,
    build_el_kamal_excel_stem,
    build_el_kamal_stem,
    export_workbook,
)
from gui.tabs.biglietti_tab import _clear_previous_client_outputs, _clear_previous_kamal_outputs


def _record(commento="PG-159640-ORD.Nr.28-2026(LETTER 108)"):
    return OrderRecord(
        customer_code="3019",
        customer_name="EL KAMAL",
        article="C170026S",
        description="Blue",
        additional_raw=commento,
        color_code="790001",
        color_name="Blue",
        order_no="28",
        order_row="1",
        colored_batch="159640",
        raw_batch="159640",
        quantity_cones=56,
        raw_weight=52.5,
        dispo="D-00505582-001",
        bagno="T1303",
        delivery="20/10/2026",
        machine="3",
        title="50/1",
        commento=commento,
        kg=52.5,
    )


def test_kamal_output_stems_follow_requested_names():
    records = [_record()]
    assert build_el_kamal_excel_stem(records) == "ORD.Nr.28-2026(LETTER 108)"
    assert build_el_kamal_stem(records) == "D-505582-KAMAL-2026"


def test_kamal_kg_converts_erp_tenths_without_touching_decimal_values():
    assert _kamal_kg(525) == 52.5
    assert _kamal_kg("525") == 52.5
    assert _kamal_kg("52.5") == 52.5
    assert _kamal_kg("52,5") == 52.5


def test_kamal_workbook_can_hide_rocche_and_kg(tmp_path):
    path = tmp_path / "kamal.xlsx"
    record = _record()
    record.vmm22 = 49.25
    export_workbook(path, [record], [], customer="EL_KAMAL", hide_kamal_quantities=True)
    ws = openpyxl.load_workbook(path, data_only=True)["EL_KAMAL"]
    header = [cell.value for cell in ws[1]]
    row = {header[i]: ws.cell(row=2, column=i + 1).value for i in range(len(header))}
    assert row["Rocche"] is None and row["KG"] is None and row["VMM22"] is None

    export_workbook(path, [record], [], customer="EL_KAMAL", hide_kamal_quantities=False)
    ws = openpyxl.load_workbook(path, data_only=True)["EL_KAMAL"]
    header = [cell.value for cell in ws[1]]
    row = {header[i]: ws.cell(row=2, column=i + 1).value for i in range(len(header))}
    assert row["Rocche"] == 56 and row["KG"] == 52.5 and row["VMM22"] == 49.25


def test_kamal_previous_generated_files_are_removed_but_unrelated_files_remain(tmp_path):
    old_excel = tmp_path / "ORD.Nr.27-2026(LETTER 107)_EL_KAMAL.xlsx"
    old_word = tmp_path / "D-505581-KAMAL-2026_Biglietti.docx"
    unrelated = tmp_path / "keep_me.xlsx"
    for path in (old_excel, old_word, unrelated):
        path.write_text("x", encoding="utf-8")

    current = tmp_path / "ORD.Nr.28-2026(LETTER 108)_EL_KAMAL.xlsx"
    _clear_previous_kamal_outputs(tmp_path, {current})

    assert not old_excel.exists() and not old_word.exists()
    assert unrelated.exists()


def test_elvy_and_med_previous_generated_files_are_removed_per_customer(tmp_path):
    old_elvy = tmp_path / "PO-27_ELVY.xlsx"
    old_med = tmp_path / "PO-27_MED_Biglietti.docx"
    other_customer = tmp_path / "PO-27_MED.xlsx"
    unrelated = tmp_path / "keep_me.xlsx"
    for path in (old_elvy, old_med, other_customer, unrelated):
        path.write_text("x", encoding="utf-8")

    _clear_previous_client_outputs(tmp_path, "ELVY")
    assert not old_elvy.exists()
    assert old_med.exists() and other_customer.exists() and unrelated.exists()

    _clear_previous_client_outputs(tmp_path, "MED")
    assert not old_med.exists() and not other_customer.exists()
    assert unrelated.exists()


def test_erp_and_filato_exports_do_not_leave_previous_workbooks(tmp_path):
    from pipelines.ordini_elvy import OrdiniElvyRow, RawYarnMatch, export_filato_full, export_ordini_full

    erp_path = tmp_path / "EXCEL PER ORDINE VENDITA EGITTO.xlsx"
    filato_path = tmp_path / "Filato x Tinturia.xlsx"
    export_ordini_full(erp_path, [OrdiniElvyRow(articolo_delta="C130001S", coloredfm="1")])
    export_ordini_full(erp_path, [OrdiniElvyRow(articolo_delta="C130002S", coloredfm="2")])
    export_filato_full(filato_path, [RawYarnMatch(articolo="G130001S", partita="1")])
    export_filato_full(filato_path, [RawYarnMatch(articolo="G130002S", partita="2")])

    assert not (tmp_path / "EXCEL PER ORDINE VENDITA EGITTO.previous.xlsx").exists()
    assert not (tmp_path / "Filato x Tinturia.previous.xlsx").exists()
