"""Ordine Elvy writes Prezzi-PO-<PO>.xlsx next to its order Excel (end to end, PDF parsing stubbed)."""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import openpyxl
import pytest

from gui.workflows.purchase_orders import PurchaseOrderWorkflowMixin
from parsers.pdf_parser import OrderRow


class _Harness(PurchaseOrderWorkflowMixin, ttk.Frame):
    """Just enough of the main window for _run_po_conversion."""

    def __init__(self, root):
        super().__init__(root)
        self._prezzi_tab = SimpleNamespace(prezzi_df=None)
        self.done = None

    def _set_po_status(self, text): pass
    def _advance_po_progress(self): pass
    def _on_po_conversion_done(self, errors, total): self.done = (errors, total)


def _rows(pod_no, pos_colours):
    return [
        OrderRow(pod_no=pod_no, pos=pos, article_no="A1", colour=name, ne="120/2", yarn="Y", dye_type="R",
                 quantity_cones=cones, abbina=f"Machine {cap} Cones")
        for pos, name, cones, cap in pos_colours
    ]


@pytest.fixture()
def harness(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    pdfs = {
        "a.pdf": _rows("1500", [(10, "AZZURRINO", 72, 72), (20, "ACHILLEA", 24, 24)]),
        "b.pdf": _rows("1501", [(10, "NERO", 128, 128)]),
    }
    monkeypatch.setattr("parsers.pdf_parser.PDFParser", lambda path: SimpleNamespace(parse=lambda: pdfs[path.name]))
    monkeypatch.setattr("parsers.elvy_mapping.load_elvy_mapping", lambda *a, **k: {})
    monkeypatch.setattr("parsers.elvy_mapping.lookup_articolo_delta", lambda article_no, mapping: "G170115S")
    monkeypatch.setattr("parsers.dfm_lookup.load_dfm_cache", lambda *a, **k: {"entries": [
        {"articolo": "C170115S", "titolo": "120/2 ORGANIC", "coloredfm": "1", "cldescr": "X"}]})
    codes = {"AZZURRINO": "343", "ACHILLEA": "895", "NERO": "372"}
    monkeypatch.setattr("parsers.dfm_lookup.lookup_dfm_color", lambda art, colour, *a: (codes[colour], colour))
    monkeypatch.setattr("parsers.dfm_lookup.is_first_time_dyeing", lambda *a: False)
    monkeypatch.setattr("calculate.prezzi.build_price_lookup", lambda df: {
        ("C170115S", "343"): (60, 4.59), ("C170115S", "895"): (71, 6.16)})   # NERO has no price
    yield _Harness(root), root
    root.destroy()


def _prezzi_files(folder):
    return sorted(p.name for p in folder.glob("Prezzi-PO*.xlsx"))


def test_merged_mode_writes_one_prezzi_po_with_every_po_number(harness, tmp_path):
    ui, root = harness
    ui._run_po_conversion([tmp_path / "a.pdf", tmp_path / "b.pdf"], tmp_path, False, False, False, None, None)
    for _ in range(20):
        root.update()
        time.sleep(0.01)
    assert ui.done == ([], 2)
    assert (tmp_path / "Ordine_Elvy.xlsx").is_file()
    assert _prezzi_files(tmp_path) == ["Prezzi-PO-1500 & 1501.xlsx"]
    ws = openpyxl.load_workbook(tmp_path / "Prezzi-PO-1500 & 1501.xlsx")["ELVY"]
    rows = [[c.value for c in row] for row in ws.iter_rows(min_row=2)]
    # Riga, ARTICOLO, TITOLO, COLORE, Q.TA, DESCR COL, LIVELLO, M/C, PREZZO, prezzo + (2$)
    assert rows[0] == [10, "C170115S", "120/2 ORGANIC", "343", 72, "AZZURRINO", 60, 72, 4.59, 4.59]
    assert rows[1] == [20, "C170115S", "120/2 ORGANIC", "895", 24, "ACHILLEA", 71, 24, 6.16, 8.16]   # 24-cone machine: +2$
    assert rows[2][3:] == ["372", 128, "NERO", None, 128, None, None]                             # no price: empty


def test_one_file_per_pdf_writes_one_prezzi_po_per_po(harness, tmp_path):
    ui, root = harness
    ui._run_po_conversion([tmp_path / "a.pdf", tmp_path / "b.pdf"], tmp_path, True, False, False, None, None)
    for _ in range(20):
        root.update()
        time.sleep(0.01)
    assert ui.done == ([], 2)
    assert _prezzi_files(tmp_path) == ["Prezzi-PO-1500.xlsx", "Prezzi-PO-1501.xlsx"]
