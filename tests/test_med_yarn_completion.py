from datetime import datetime, timedelta

import openpyxl
import pandas as pd

from pipelines.ordine_med import (
    FilatoInventory,
    OrdineMedRow,
    assign_consegna,
    compute_filato_availability,
    compute_data_riconsegna,
    export_filato_availability_workbook,
    export_erp_order_workbook,
    export_ordine_med_workbook,
    load_filato_inventory,
)


def _med_row(*, row_number=1, pt_grg="159600", rocc=10, nota_grg=""):
    return OrdineMedRow(
        riga=row_number,
        code_org="C010937S",
        titolo="120/2 ORGANIC",
        descr_col="AZZURRINO",
        articolo="C010937S",
        colore="343",
        rocc=rocc,
        abbin=None,
        consegna_input=None,
        pt_grg=pt_grg,
        pt_med="",
        polmoni="",
        cliente_note="",
        nota_grg=nota_grg,
        nota_col="",
        kg_note="",
        fabb="",
        prezz_note="",
    )


def test_med_shortage_is_completed_from_alternative_pt_grg_in_nota_grg():
    rows = [
        _med_row(row_number=1, rocc=10, nota_grg="+159685 159877+"),
        _med_row(row_number=2, rocc=6, nota_grg="raw 159877"),
    ]

    (availability,) = compute_filato_availability(
        rows,
        densita_map=None,
        stock_map={159600: 12, 159685: 3, 159877: 5},
    )

    assert availability.rocche == 16
    assert availability.manca == -4
    assert availability.completamento_pt_1 == 159685
    assert availability.completamento_rocche_1 == 3
    assert availability.completamento_pt_2 == 159877
    assert availability.completamento_rocche_2 == 1


def test_med_filato_workbooks_include_completion_columns_and_quantities(tmp_path):
    rows = [_med_row(rocc=10, nota_grg="+159685")]
    (availability,) = compute_filato_availability(
        rows,
        densita_map=None,
        stock_map={159600: 7, 159685: 4},
    )

    order_file = tmp_path / "Ordine_MED.xlsx"
    export_ordine_med_workbook(order_file, rows, [availability])
    workbook = openpyxl.load_workbook(order_file, data_only=True)
    sheet = workbook["Filato X Tinturia"]
    values = {cell.value: sheet.cell(2, cell.column).value for cell in sheet[1]}
    workbook.close()
    assert values["تكمله من خام"] == 159685
    assert values["عدد."] == 3
    assert values["Custom"] == "تحضير خام"

    filato_file = tmp_path / "Filato X Tinturia.xlsx"
    export_filato_availability_workbook(filato_file, [availability], source_path=order_file)
    workbook = openpyxl.load_workbook(filato_file, data_only=True)
    sheet = workbook["Filato X Tinturia"]
    values = {cell.value: sheet.cell(2, cell.column).value for cell in sheet[1]}
    assert sheet["G1"].value == "تكمله من خام"
    assert sheet["H1"].value == "عدد."
    assert sheet["F2"].value == "تحضير خام"
    assert sheet["F2"].font.bold is True
    workbook.close()
    assert values["تكمله من خام"] == 159685
    assert values["عدد."] == 3


def test_med_does_not_assign_alternative_yarn_when_primary_stock_is_enough():
    (availability,) = compute_filato_availability(
        [_med_row(rocc=10, nota_grg="+159685")],
        densita_map=None,
        stock_map={159600: 10, 159685: 4},
    )

    assert availability.completamento_pt_1 is None
    assert availability.completamento_rocche_1 is None


def test_med_empty_nota_uses_available_batch_with_the_same_lotto():
    inventory = FilatoInventory(
        stock_by_partita={159600: 7, 159601: 5},
        stock_by_article_partita={
            ("G010937S", 159600): 7,
            ("G010937S", 159601): 5,
        },
        lotto_by_partita={159600: "LOT-A", 159601: "LOT-A"},
    )
    (availability,) = compute_filato_availability(
        [_med_row(rocc=10)],
        densita_map=None,
        stock_map=inventory,
    )

    assert availability.completamento_pt_1 == 159601
    assert availability.completamento_rocche_1 == 3


def test_med_filato_inventory_loads_partita_stock_and_lotto_snapshots(monkeypatch):
    from utility import source_manager

    snapshots = {
        "magazino_summary": pd.DataFrame([
            {"articolo": "G010937S", "partita": "159600", "mag_rocche": 7, "mag_peso": 10},
            {"articolo": "G010937S", "partita": "159601", "mag_rocche": 5, "mag_peso": 8},
        ]),
        "lotti_summary": pd.DataFrame([
            {"partita": "159600", "lotto": "LOT-A"},
            {"partita": "159601", "lotto": "LOT-A"},
        ]),
    }
    monkeypatch.setattr(source_manager, "load", lambda name: snapshots[name])

    inventory = load_filato_inventory()

    assert inventory.stock_by_article_partita == {
        ("G010937S", 159600): 7,
        ("G010937S", 159601): 5,
    }
    assert inventory.lotto_by_partita == {159600: "LOT-A", 159601: "LOT-A"}


def test_med_filato_inventory_reads_a_magazino_summary_workbook(tmp_path, monkeypatch):
    from utility import source_manager

    magazino_file = tmp_path / "Magazino.xlsx"
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    sheet.title = "Magazino"
    sheet.append(["Articolo", "Partita", "Mag.rocche", "Mag.peso"])
    sheet.append(["G010937S", 159685, 6, 9.5])
    workbook.save(magazino_file)
    workbook.close()
    monkeypatch.setattr(source_manager, "load", lambda _name: None)

    inventory = load_filato_inventory(magazino_file)

    assert inventory.stock_by_article_partita == {("G010937S", 159685): 6}


def test_med_customer_lot_is_excluded_unless_it_exists_in_filato_stock():
    rows = [
        _med_row(row_number=1, pt_grg="837756", rocc=4),
        _med_row(row_number=2, pt_grg="159600", rocc=10),
    ]
    inventory = FilatoInventory(
        stock_by_partita={159600: 10},
        stock_by_article_partita={("G010937S", 159600): 10},
        lotto_by_partita={},
    )
    primary_only = compute_filato_availability(rows, None, inventory)
    assert [row.pt_grg for row in primary_only] == [159600]

    inventory.stock_by_partita[837756] = 4
    inventory.stock_by_article_partita[("G010937S", 837756)] = 4
    stocked_customer_lot = compute_filato_availability(rows, None, inventory)
    assert {row.pt_grg for row in stocked_customer_lot} == {159600, 837756}


def test_med_next_filato_export_replaces_previous_order_rows_and_completions(tmp_path):
    filato_file = tmp_path / "Filato X Tinturia.xlsx"
    first = compute_filato_availability(
        [_med_row(rocc=10, nota_grg="159685")],
        None,
        {159600: 7, 159685: 4},
    )
    export_filato_availability_workbook(filato_file, first)

    second = compute_filato_availability(
        [_med_row(pt_grg="159700", rocc=3)],
        None,
        {159700: 3},
    )
    export_filato_availability_workbook(filato_file, second)

    workbook = openpyxl.load_workbook(filato_file, data_only=True)
    sheet = workbook["Filato X Tinturia"]
    values = {cell.value: sheet.cell(2, cell.column).value for cell in sheet[1]}
    workbook.close()
    assert sheet.max_row == 2
    assert values["PT GRG"] == 159700
    assert values["تكمله من خام"] is None


def test_med_consegna_uses_machine_coverage_plus_14_days_and_keeps_later_input(monkeypatch):
    from calculate import situazione

    monkeypatch.setattr(situazione, "machine_number_from_label", lambda _value: 5)
    monkeypatch.setattr(situazione, "machine_coverage_until", lambda _count: "2026-11-05")
    rows = [
        _med_row(row_number=1, rocc=10),
        _med_row(row_number=2, rocc=10),
    ]
    rows[0].gruppo_macchina = 3301
    rows[1].gruppo_macchina = 3301
    rows[1].consegna_input = datetime(2026, 11, 30)

    assign_consegna(rows, {5: 8})
    compute_data_riconsegna(rows)

    assert rows[0].consegna == datetime(2026, 11, 19)
    assert rows[0].data_riconsegna == datetime(2026, 11, 18)
    assert rows[1].consegna == datetime(2026, 11, 30)
    assert rows[1].data_riconsegna == datetime(2026, 11, 29)


def test_med_consegna_without_machine_or_input_defaults_to_today_plus_14_days():
    record = _med_row()

    assign_consegna([record], {})

    assert record.consegna.date() == datetime.now().date() + timedelta(days=14)


def test_med_erp_export_shows_real_dates_as_day_month_year(tmp_path):
    from exporters.master_formats import ERP_HEADERS

    record = _med_row()
    record.consegna = datetime(2026, 11, 19)
    record.data_riconsegna = datetime(2026, 11, 18)
    target = tmp_path / "system.xlsx"
    export_erp_order_workbook(target, [record])

    workbook = openpyxl.load_workbook(target, data_only=True)
    sheet = workbook["Foglio1"]
    values = {cell.value: sheet.cell(2, cell.column).value for cell in sheet[1]}
    formats = {cell.value: sheet.cell(2, cell.column).number_format for cell in sheet[1]}
    workbook.close()
    assert tuple(values) == ERP_HEADERS
    assert values["CONSEGNA"] == datetime(2026, 11, 19)
    assert values["DATA RICONSEGNA"] == datetime(2026, 11, 18)
    assert formats["CONSEGNA"] == "dd/mm/yyyy"
    assert formats["DATA RICONSEGNA"] == "dd/mm/yyyy"
