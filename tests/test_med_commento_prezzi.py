"""Ordine MED: the PT GRG -> Commento rule, Show Orders filing, and the Prezzi file."""
import openpyxl
import pytest

from exporters.biglietti_exporter import (
    _is_pg_x,
    export_workbook,
    load_order,
    requested_lotto_for,
    requested_lotto_from_comment,
)
from pipelines.ordine_med import (
    PREZZI_HEADERS,
    OrdineMedRow,
    compute_commento,
    export_prezzi_workbook,
    pg_token,
)


def _med(**kw):
    base = dict(
        riga=1, code_org="C010937S", titolo="120/2 ORGANIC", descr_col="AZZURRINO", articolo="C010937S",
        colore="343", rocc=72, abbin=None, consegna_input=None, pt_grg="", pt_med="", polmoni="",
        cliente_note="", nota_grg="", nota_col="", kg_note="", fabb="", prezz_note="",
        mc=72, livello=60, prezzo=4.59, prezzo_plus2=4.59,
    )
    base.update(kw)
    return OrdineMedRow(**base)


# ------------------------------------------------------------------ Commento
@pytest.mark.parametrize("pt_grg, expected", [
    ("", "X"),                       # nothing yet
    ("159266", "159266"),            # starts with 1: the customer's lot
    ("837756", "X(837756)"),         # any other number: a raw reference, still waiting
    (837756, "X(837756)"),           # numeric cell
    ("837756.0", "X(837756)"),       # Excel float
    ("100", "100"),
    ("X", "X"),                      # not a number: untouched
])
def test_pg_token(pt_grg, expected):
    assert pg_token(pt_grg) == expected


def test_commento_keeps_the_rest_of_the_data_as_it_was():
    rows = [
        _med(pt_grg="837756", pt_med="M5", polmoni="POLM", cliente_note="CLI", nota_col="NOTA"),
        _med(pt_grg="159266"),
        _med(pt_grg=""),
    ]
    compute_commento(rows)
    assert [r.commento for r in rows] == [
        "PG-X(837756)-PM-M5-POLM-CLI-NOTA",
        "PG-159266-PM-X",
        "PG-X-PM-X",
    ]


# ------------------------------------------------------------------ Show Orders filing
def test_raw_batch_helpers_tell_our_batch_from_the_med_customer_lot():
    from calculate.raw_batch import is_assigned_raw, is_blank_raw, is_customer_lot

    for blank in ("", None, "X", "pg-x", " PGX "):
        assert is_blank_raw(blank) and not is_assigned_raw(blank, "3004")
    assert is_assigned_raw("159233", "3004") and not is_customer_lot("159233", "3004")
    assert is_customer_lot("837756", "3004") and not is_assigned_raw("837756", "3004")
    # other customers: any recorded batch is a real one (their numbers may not start with 1)
    assert is_assigned_raw("79228", "3009") and is_assigned_raw("837756", "3019")


def test_the_med_batch_comes_only_from_the_comment_including_med_customer_lots():
    from exporters.biglietti_exporter import _med_raw_batch

    assert _med_raw_batch("PG-159233-PM-X") == "159233"          # our raw batch: assigned
    assert _med_raw_batch("PG-X(837756)-PM-X") == "837756"       # shown, but still in PG-X
    assert _med_raw_batch("PG-837756-PM-X") == "837756"
    assert _med_raw_batch("PG-X-PM-X") == "" and _med_raw_batch("") == ""


def test_the_lotto_to_look_for_in_the_stock():
    assert requested_lotto_from_comment("PG-159233-PM-X") == "159233"
    assert requested_lotto_from_comment("PG-X(837756)-PM-X") == "837756"
    assert requested_lotto_from_comment("PG-X-PM-X") == ""
    assert requested_lotto_from_comment("") == ""


def test_load_order_med_rows_keep_customer_lots_and_file_them_in_pg_x(tmp_path):
    """MED lots come only from the comment; customer lots remain in PG-X."""
    from tests.test_report_fixes import _kamal_erp_dump
    data = tmp_path / "ORD.xlsx"
    _kamal_erp_dump(data, [
        (3004, "C010937S", 343, 1, 159527, 72, "PG-159233-PM-X"),         # our raw batch
        (3004, "C010937S", 372, 2, 159528, 128, "PG-X(837756)-PM-X"),     # customer lot
        (3004, "C010937S", 527, 3, 159529, 72, "PG-X-PM-X"),              # nothing yet
        (3009, "C130027S", 304, 4, 159530, 24, "PG-X-PO-1-2026"),         # ELVY is untouched
    ])
    records, _ = load_order(data, None)
    assert [r.raw_batch for r in records] == ["159233", "837756", "", ""]
    assert [_is_pg_x(r.raw_batch, r.customer_code) for r in records] == [False, True, True, True]
    assert [r.customer_code for r in records] == ["3004", "3004", "3004", "3009"]


def test_med_customer_lot_keeps_lookup_data_but_is_not_filato(tmp_path):
    from tests.test_report_fixes import _kamal_erp_dump
    from exporters.biglietti_exporter import _filato_rows, append_create_excel, enrich_records, load_create_excel_records
    data = tmp_path / "ORD.xlsx"
    _kamal_erp_dump(data, [(3004, "C010937S", 372, 2, 159528, 128, "PG-X(837756)-PM-X")])
    (record,), _ = load_order(data, None)
    enrich_records([record], "MED",
                   densita_map={837756: {"peso_net": 1.5, "densita": 380, "color_tube": "T1"}},
                   vmm_ratio_map={837756: 0.4})
    assert record.raw_batch == "837756"
    assert record.kg == 192 and record.vmm22 == 51.2
    assert record.densita == 380 and record.color_tube == "T1"
    assert _filato_rows([record], [], magazino_summary=None) == []

    shared = tmp_path / "Show Orders.xlsx"
    append_create_excel(shared, [record], "MED")
    assert load_create_excel_records(shared, sheet_name="Orders") == []
    pg_x = load_create_excel_records(shared, sheet_name="PG-X")
    assert len(pg_x) == 1 and pg_x[0].raw_batch == "837756"


# ------------------------------------------------------------------ Prezzi.xlsx
def test_prezzi_workbook_has_the_requested_columns_in_order(tmp_path):
    rows = [_med(riga=1, prezzo=4.59, prezzo_plus2=4.59),
            _med(riga=4, colore="895", rocc=24, mc=24, livello=71, prezzo=6.16, prezzo_plus2=8.16, descr_col="ACHILLEA"),
            _med(riga=9, colore="1040", prezzo="", prezzo_plus2="")]
    path = tmp_path / "Prezzi.xlsx"
    export_prezzi_workbook(path, rows)
    wb = openpyxl.load_workbook(path)
    assert wb.sheetnames == ["MED"]
    ws = wb["MED"]
    assert [c.value for c in ws[1]] == PREZZI_HEADERS == [
        "Riga", "ARTICOLO", "TITOLO", "COLORE", "Q.TA", "DESCR COL", "LIVELLO", "M/C", "PREZZO", "prezzo + (2$)",
    ]
    assert [c.value for c in ws[3]] == [4, "C010937S", "120/2 ORGANIC", "895", 24, "ACHILLEA", 71, 24, 6.16, 8.16]
    assert ws["I4"].value is None and ws["J4"].value is None           # no price found -> empty cell
    assert ws["I2"].number_format == "0.00"
    assert ws.freeze_panes == "A2" and ws.auto_filter.ref


# ------------------------------------------------------------------ Kamal Excel: no VMM22
def test_kamal_sheet_has_no_vmm22_column_but_the_other_customers_keep_it(tmp_path):
    from tests.test_kamal_output_updates import _record

    kamal = _record()
    kamal.vmm22 = 49.25
    path = tmp_path / "k.xlsx"
    export_workbook(path, [kamal], [], customer="EL_KAMAL")
    assert "VMM22" not in [c.value for c in openpyxl.load_workbook(path)["EL_KAMAL"][1]]

    elvy = _record()
    elvy.customer_code = "3009"
    elvy.vmm22 = 49.25
    export_workbook(path, [elvy], [], customer="ELVY")
    assert "VMM22" in [c.value for c in openpyxl.load_workbook(path)["ELVY"][1]]


# ------------------------------------------------------------------ Smart Auto-Assign / Print Assigned PG-X
def _shared_record(customer_code, raw_batch, commento="PG-X-PM-X"):
    from exporters.biglietti_exporter import OrderRecord
    return OrderRecord(
        customer_code=customer_code, customer_name="MED" if customer_code == "3004" else "ELVY",
        article="C010937S", description="", additional_raw=commento, color_code="343", color_name="X",
        order_no="1", order_row="1", colored_batch="159527", raw_batch=raw_batch, quantity_cones=72,
        raw_weight=None, dispo="", bagno="", delivery="", machine="", title="", commento=commento,
    )


def test_smart_auto_assign_takes_the_med_lot_from_partita_gg_or_the_comment():
    # a customer lot typed where Partita GG goes wins; otherwise the comment's lotto is used
    assert requested_lotto_for(_shared_record("3004", "837756", "PG-X-PM-X")) == "837756"
    assert requested_lotto_for(_shared_record("3004", "", "PG-X(837756)-PM-X")) == "837756"
    assert requested_lotto_for(_shared_record("3004", "", "PG-X-PM-X")) == ""
    assert requested_lotto_for(_shared_record("3009", "", "PG-X-PO-1-2026")) == ""


def test_print_assigned_pg_x_prints_only_rows_holding_one_of_our_batches():
    from gui.tabs.shared_order_actions import SharedOrdersActionsMixin

    records = {
        "a": _shared_record("3004", "159233"),      # MED, our raw batch      -> printed
        "b": _shared_record("3004", "837756"),      # MED, the customer's lot -> still waiting
        "c": _shared_record("3004", ""),            # MED, nothing yet        -> waiting
        "d": _shared_record("3009", "79228"),       # ELVY, any recorded batch counts
        "e": _shared_record("3004", "159240"),      # on the Orders sheet, not PG-X
    }
    sheets = {"a": "PG-X", "b": "PG-X", "c": "PG-X", "d": "PG-X", "e": "Orders"}
    chosen = SharedOrdersActionsMixin._assigned_pgx_records(None, "PG-X", records, sheets)
    assert [r.raw_batch for r in chosen] == ["159233", "79228"]
    assert SharedOrdersActionsMixin._assigned_pgx_records(None, "Orders", records, sheets) == []


def test_ready_and_pg_x_ticket_split_follows_the_same_rule():
    from gui.tabs.biglietti_tab import _split_pg_x_records

    ready, waiting = _split_pg_x_records([
        _shared_record("3004", "159233"), _shared_record("3004", "837756"), _shared_record("3004", ""),
    ])
    assert [r.raw_batch for r in ready] == ["159233"]
    assert [r.raw_batch for r in waiting] == ["837756", ""]


def test_med_batch_ignores_a_comment_token_that_is_not_a_number():
    from exporters.biglietti_exporter import _med_raw_batch

    assert _med_raw_batch("PG-ABC-PM-X") == "" and _med_raw_batch("PG-12A-PM-X") == ""
    assert _med_raw_batch("PG-X(837756)-PM-X") == "837756"


def test_the_shared_excel_migration_moves_med_customer_lots_to_pg_x_but_not_other_customers(tmp_path):
    """A MED row left on Orders with a customer lot goes back to PG-X on the next import;
    a batch that does not start with 1 is only a customer lot for MED."""
    from dataclasses import replace

    from exporters.biglietti_exporter import append_create_excel, load_create_excel_records

    shared = tmp_path / "Show Orders.xlsx"
    med_ours = replace(_shared_record("3004", "159233"), colored_batch="159001", order_no="1")
    med_lot = replace(_shared_record("3004", "159240"), colored_batch="159002", order_no="2")
    elvy = replace(_shared_record("3009", "159250"), colored_batch="159003", order_no="3")
    append_create_excel(shared, [med_ours, med_lot, elvy], "MED")

    wb = openpyxl.load_workbook(shared)
    ws = wb["Orders"]
    headers = [c.value for c in ws[1]]
    raw_col, partita_col = headers.index("Partita GG") + 1, headers.index("Partita Col") + 1
    for row in range(2, ws.max_row + 1):
        partita = str(ws.cell(row=row, column=partita_col).value)
        ws.cell(row=row, column=raw_col).value = {"159002": "837756", "159003": "79228"}.get(partita, ws.cell(row=row, column=raw_col).value)
    wb.save(shared)
    wb.close()

    extra = replace(_shared_record("3004", "159260"), colored_batch="159004", order_no="4")
    append_create_excel(shared, [extra], "MED")            # any import runs the migration

    orders = {r.colored_batch for r in load_create_excel_records(shared, sheet_name="Orders")}
    pg_x = {r.colored_batch for r in load_create_excel_records(shared, sheet_name="PG-X")}
    assert "159002" in pg_x and "159002" not in orders       # MED customer lot -> PG-X
    assert "159003" in orders and "159003" not in pg_x       # ELVY keeps any recorded batch on Orders
    assert {"159001", "159004"} <= orders
