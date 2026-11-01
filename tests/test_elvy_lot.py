"""Ordine Elvy raw-yarn lot: parsing, lot -> article -> PG-X(lot) matching, and the MED-style
handling in Create (EXCEL+Biglietti), Show Orders and Situazione."""
import time
import tkinter as tk
from dataclasses import replace

import openpyxl
import pandas as pd
import pytest

from calculate.raw_batch import is_assigned_raw, is_customer_lot
from exporters.biglietti_exporter import (
    _commento_for,
    _filato_rows,
    _raw_batch_from_comment,
    load_order,
    requested_lotto_for,
)
from exporters.excel_exporter import ExcelExporter
from parsers.pdf_parser import OrderRow
from pipelines.ordini_elvy import build_ordini_elvy_rows, match_by_lot, match_raw_yarn, with_partita
from tests.test_med_commento_prezzi import _shared_record
from tests.test_report_fixes import _kamal_erp_dump
from utility.utils import split_article_description


# ------------------------------------------------------------------ the PDF "Lot :" text
def test_the_lot_is_what_follows_lot_and_stays_empty_when_nothing_does():
    full = split_article_description("100% Cotton Nm 170/2 Ne 100/2 Vat Griege Lot : 52_LOT 1251B.3")
    assert full["lot"] == "52_LOT 1251B.3" and full["yarn"] == "100% Cotton" and full["dye_type"] == "Vat"
    for text in ("100% Cotton Nm 170/2 Ne 100/2 Vat Griege Lot :", "100% Cotton Nm 170/2 Ne 100/2 Vat Griege Lot:  ",
                 "100% Cotton Nm 170/2 Ne 100/2 Vat Griege Lot"):
        parts = split_article_description(text)
        assert parts["lot"] == ""                                  # no stray ":" ...
        assert (parts["nm"], parts["ne"], parts["dye_type"]) == ("170/2", "100/2", "Vat")   # ... and the rest is still read
    assert split_article_description("Nm 1 Ne 2 Vat Lot 77A")["lot"] == "77A"        # no colon


# ------------------------------------------------------------------ the Commento and the matching
def _po_row(lot, **kw):
    base = dict(pod_no="1500", po_date="19/4/2026", pos=10, article_no="A1", colour="NERO", ne="100/2",
                articolo_delta="G170115S", coloredfm="372", quantity_cones=24, abbina="Machine 24 Cones", lot=lot)
    base.update(kw)
    return OrderRow(**base)


def test_the_commento_names_the_lot_or_just_pg_x():
    with_lot, without = build_ordini_elvy_rows([_po_row("52_LOT 1251B.3"), _po_row("")])
    assert with_lot.commento == "PG-X(52_LOT 1251B.3)-PO-1500-2026"
    assert without.commento == "PG-X-PO-1500-2026"
    assert with_partita("PG-X(AB-12)-PO-1500-2026", "159233") == "PG-159233-PO-1500-2026"
    assert with_partita("PG-X-PO-1500-2026", "159233") == "PG-159233-PO-1500-2026"


_STOCK = pd.DataFrame([
    {"articolo": "G170115S", "partita": "159233", "mag_rocche": 100.0, "mag_peso": 100.0},
    {"articolo": "G170115S", "partita": "159300", "mag_rocche": 48.0, "mag_peso": 48.0},
    {"articolo": "G999999S", "partita": "159400", "mag_rocche": 90.0, "mag_peso": 90.0},       # another article
])
_LOTTI = pd.DataFrame([
    {"partita": "159233", "lotto": "52_LOT 1251B.3"},
    {"partita": "159400", "lotto": "OTHER-ARTICLE"},
])


def test_a_lot_in_magazino_filato_is_matched_first_then_the_article_then_pg_x_lot():
    rows = build_ordini_elvy_rows([
        _po_row("52_LOT 1251B.3"),          # 1) its lot is in stock for its article
        _po_row("UNKNOWN-LOT"),             # 2) lot not found -> by article
        _po_row("OTHER-ARTICLE"),           # a lot that belongs to another article is not used
    ])
    matches = match_by_lot(rows, _STOCK, _LOTTI)
    assert [m.partita for m in matches] == ["159233"]
    assert rows[0].commento == "PG-159233-PO-1500-2026"
    assert rows[1].commento == "PG-X(UNKNOWN-LOT)-PO-1500-2026"          # still waiting
    match_raw_yarn(rows, _STOCK, None)                                    # the by-article step
    assert rows[1].commento.startswith("PG-1593") and "(" not in rows[1].commento


def test_nothing_found_keeps_pg_x_with_or_without_the_lot():
    rows = build_ordini_elvy_rows([_po_row("NOPE"), _po_row("")])
    assert match_by_lot(rows, _STOCK.iloc[0:0], _LOTTI) == [] and match_by_lot(rows, _STOCK, None) == []
    assert [r.commento for r in rows] == ["PG-X(NOPE)-PO-1500-2026", "PG-X-PO-1500-2026"]


def test_the_elvy_excel_applies_lot_then_article_then_pg_x(tmp_path):
    path = tmp_path / "elvy.xlsx"
    rows = [_po_row("52_LOT 1251B.3", pos=10), _po_row("NOPE", pos=20, coloredfm="895")]
    ExcelExporter(rows, path, _STOCK, {}, lotti_summary=_LOTTI).export()
    ws = openpyxl.load_workbook(path)["Ordini ELVY"]
    headers = [c.value for c in ws[1]]
    comments = [r[headers.index("COMMENTO")].value for r in ws.iter_rows(min_row=2)]
    assert comments[0] == "PG-159233-PO-1500-2026"                   # found by its lot
    assert comments[1].startswith("PG-159300-") or comments[1].startswith("PG-159233-")   # found by article


# ------------------------------------------------------------------ the customer-lot rule, ELVY included
def test_an_elvy_lot_is_numbers_and_letters_and_is_not_one_of_our_batches():
    assert is_customer_lot("52_LOT 1251B.3", "3009") and is_customer_lot("AB12", "3009")
    assert is_customer_lot("837756", "3009") and is_customer_lot("837756", "3004")      # numbers not starting with 1
    assert not is_customer_lot("159233", "3009") and is_assigned_raw("159233", "3009")
    assert not is_customer_lot("52_LOT", "3019")                                          # Kamal keeps any recorded batch
    assert not is_customer_lot("", "3009") and not is_customer_lot("PG-X", "3009")


def test_the_comment_gives_the_elvy_lot_and_the_med_lot_differently():
    assert _raw_batch_from_comment("PG-X(52_LOT 1251B.3)-PO-1500-2026", "3009") == "52_LOT 1251B.3"
    assert _raw_batch_from_comment("PG-X(52_LOT 1251B.3)-PM-X", "3004") == ""        # a MED lot is a number
    assert _raw_batch_from_comment("PG-X(837756)-PM-X", "3004") == "837756"
    assert _raw_batch_from_comment("PG-159233-PO-1500-2026", "3009") == "159233"
    assert _raw_batch_from_comment("PG-X-PO-1500-2026", "3009") == ""
    assert _commento_for("ELVY", "PG-X(AB-12)-PO-1500-2026") == "PO-1500-2026"          # a dash in the lot does not shift the split


def test_create_files_an_elvy_lot_row_under_pg_x_and_keeps_it_out_of_filato(tmp_path):
    data = tmp_path / "ORD.xlsx"
    _kamal_erp_dump(data, [
        (3009, "C170115S", 372, 1, 159001, 24, "PG-X(52_LOT 1251B.3)-PO-1500-2026"),
        (3009, "C170115S", 343, 2, 159002, 24, "PG-159233-PO-1500-2026"),
        (3009, "C170115S", 304, 3, 159003, 24, "PG-X-PO-1500-2026"),
    ])
    records, raw = load_order(data, None)
    assert [r.raw_batch for r in records] == ["52_LOT 1251B.3", "159233", ""]
    assert [is_assigned_raw(r.raw_batch, r.customer_code) for r in records] == [False, True, False]
    assert requested_lotto_for(records[0]) == "52_LOT 1251B.3"                         # what Smart Auto-Assign looks for
    assert all(row["Partita"] != "52_LOT 1251B.3" for row in _filato_rows(records, raw, None))


# ------------------------------------------------------------------ Situazione: red when the lot is not in stock
def test_situazione_colours_a_named_lot_that_is_not_in_stock_red():
    from gui.tabs.situazione_tab import SituazioneTab
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    try:
        tab = SituazioneTab(root)
        # keep the background SQLite / shared-source restore from replacing the frame under test
        tab._db_restore_scheduled = tab._sources_restore_started = True
        frame = pd.DataFrame([
            {"cliente": "ELVY", "articolo": "C1", "codice": "1", "comment": "PG-X(NOPE)-PO-1500-2026", "raw_yarn_match": "", "new_comment": "Filato"},
            {"cliente": "ELVY", "articolo": "C1", "codice": "2", "comment": "PG-X(52_LOT)-PO-1500-2026", "raw_yarn_match": "G1 / 159233", "new_comment": "Filato"},
            {"cliente": "ELVY", "articolo": "C1", "codice": "3", "comment": "PG-X-PO-1500-2026", "raw_yarn_match": "", "new_comment": "Filato"},
        ])
        tab.current_df = frame
        tab._render_tree(frame)
        end = time.time() + 5
        while time.time() < end and len(tab.tree.get_children()) < 3:       # rows are inserted in chunks
            root.update()
            time.sleep(0.01)
        tags = {tab.tree.set(i, "codice"): tab.tree.item(i, "tags") for i in tab.tree.get_children()}
        detail = (tags, len(tab.current_df), list(tab.current_df.get("comment", [])))
        assert "yarn_missing" in tags["1"], detail                   # named lot, nothing in stock: red
        assert "yarn_missing" not in tags["2"] and "yarn_missing" not in tags["3"], detail
    finally:
        root.destroy()


def test_one_entry_point_never_hands_the_same_batch_to_the_lot_and_the_article_step():
    """match_raw_yarn(lotti_summary=...): the batch the lot step takes is deducted before the
    by-article step runs, so two rows of the same lot do not both get it."""
    rows = build_ordini_elvy_rows([_po_row("52_LOT 1251B.3", quantity_cones=100), _po_row("52_LOT 1251B.3", pos=20, quantity_cones=40)])
    matches = match_raw_yarn(rows, _STOCK, None, lotti_summary=_LOTTI)
    partitas = [r.commento.split("-")[1] for r in rows]
    assert partitas[0] == "159233"                      # the whole lot batch (100 cones) went to the first row
    assert partitas[1] == "159300"                      # the second row falls to the other batch of its article
    assert sorted(m.partita for m in matches) == ["159233", "159300"]
