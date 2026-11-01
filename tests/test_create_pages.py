"""Create (EXCEL+Biglietti): one conversion per customer, the separate Show Orders page, and
the "choose the Show Orders workbook first" warning."""
import time
import tkinter as tk
from tkinter import ttk
from types import SimpleNamespace

import openpyxl
import pytest
from docx import Document

from pipelines.create_conversion import (
    CommonSources,
    ConversionRequest,
    convert_customer,
    customer_records,
)
from tests.test_report_fixes import _kamal_erp_dump


def _template(path):
    """A minimal Biglietti.docx: one ticket table with the 11 rows the exporter fills."""
    document = Document()
    table = document.add_table(rows=11, cols=4)
    for row in table.rows:
        for cell in row.cells:
            cell.text = "x"
    document.save(path)
    return path


@pytest.fixture()
def dump(tmp_path):
    """An ERP dump holding ELVY (3009), MED (3004) and EL KAMAL (3019) rows."""
    path = tmp_path / "ORD.xlsx"
    _kamal_erp_dump(path, [
        (3009, "C130027S", 304, 1, 159001, 72, "PG-X-PO-1500-2026"),
        (3009, "C130027S", 305, 2, 159002, 24, "PG-X-PO-1501-2026"),
        (3004, "C010937S", 343, 3, 159003, 72, "PG-X(837756)-PM-X"),
        (3004, "C010937S", 372, 4, 159004, 128, "PG-159233-PM-X"),
        (3019, "C170115S", 790351, 5, 159005, 330, "PG-1-ORD.Nr.28-2026(LETTER 108)"),
    ])
    return path


def _request(kind, dump, tmp_path, **kw):
    out = tmp_path / f"out_{kind}"
    out.mkdir(exist_ok=True)
    base = dict(kind=kind, data_path=dump, dispo_path=None, template=_template(tmp_path / "Biglietti.docx"), output_dir=out)
    base.update(kw)
    return ConversionRequest(**base)


# ---------------------------------------------------------------- the conversion service
def test_customer_records_keeps_only_the_requested_customer(dump):
    for kind, expected in (("elvy", 2), ("med", 2), ("el_kamal", 1)):
        records, _raw, _format = customer_records(kind, dump, None)
        assert len(records) == expected
        assert {r.customer_code for r in records} == {{"elvy": "3009", "med": "3004", "el_kamal": "3019"}[kind]}


def test_a_file_without_the_customer_is_refused(tmp_path):
    only_elvy = tmp_path / "ELVY.xlsx"
    _kamal_erp_dump(only_elvy, [(3009, "C130027S", 304, 1, 159001, 72, "PG-X-PO-1500-2026")])
    with pytest.raises(ValueError, match="MED"):
        customer_records("med", only_elvy, None)


def test_elvy_conversion_writes_only_elvy_files_named_from_the_commento(dump, tmp_path):
    shared = tmp_path / "Show Orders.xlsx"
    request = _request("elvy", dump, tmp_path, shared_excel=shared)
    earlier = request.output_dir / "PO-1-2025.xlsx"                  # an earlier order's file
    earlier.write_text("keep me", encoding="utf-8")

    result = convert_customer(request, CommonSources())
    names = sorted(p.name for p in request.output_dir.iterdir())
    assert "PO-1500 & 1501-2026.xlsx" in names and "PO-1500 & 1501-2026-pg-x.docx" in names
    assert earlier.exists()                                           # never deleted
    assert not any("MED" in n or "KAMAL" in n for n in names)         # no other customer's file
    assert result.tickets == 2
    wb = openpyxl.load_workbook(shared)
    assert wb["PG-X"].max_row == 3                                    # header + the two waiting ELVY rows
    assert "Shared Excel" in result.items[0]


def test_med_conversion_files_the_customer_lot_row_under_pg_x(dump, tmp_path):
    shared = tmp_path / "Show Orders.xlsx"
    result = convert_customer(_request("med", dump, tmp_path, shared_excel=shared), CommonSources())
    out = tmp_path / "out_med"
    stem = next(p.name for p in out.glob("*_MED.xlsx"))
    assert stem.startswith("MED-") and (out / stem.replace(".xlsx", ".docx")).exists()
    wb = openpyxl.load_workbook(shared)
    headers = [c.value for c in wb["Orders"][1]]
    pg_x_partitas = {str(r[headers.index("Partita Col")].value) for r in wb["PG-X"].iter_rows(min_row=2)}
    orders_partitas = {str(r[headers.index("Partita Col")].value) for r in wb["Orders"].iter_rows(min_row=2)}
    assert pg_x_partitas == {"159003"} and orders_partitas == {"159004"}      # customer lot waits; ours is ready
    assert result.tickets == 2


def test_kamal_conversion_needs_no_show_orders_workbook(dump, tmp_path):
    request = _request("el_kamal", dump, tmp_path)
    result = convert_customer(request, CommonSources())
    names = sorted(p.name for p in request.output_dir.iterdir())
    assert any(n.endswith("_EL_KAMAL.xlsx") for n in names)
    assert any(n.endswith(".docx") and "Biglietti" not in n for n in names)
    assert result.tickets == 1


def test_filato_file_is_per_customer_and_not_part_of_the_email_files(dump, tmp_path):
    filato_dir = tmp_path / "filato_elvy"
    request = _request("elvy", dump, tmp_path, shared_excel=tmp_path / "S.xlsx", filato_dir=filato_dir)
    result = convert_customer(request, CommonSources())
    assert result.filato_file is None or result.filato_file.parent == filato_dir   # only written when raw rows exist
    assert result.filato_file not in result.files


def test_a_missing_template_is_reported(dump, tmp_path):
    request = _request("elvy", dump, tmp_path, shared_excel=tmp_path / "S.xlsx")
    request = ConversionRequest(**{**request.__dict__, "template": tmp_path / "nope.docx"})
    with pytest.raises(ValueError, match="template"):
        convert_customer(request, CommonSources())


# ---------------------------------------------------------------- the page
@pytest.fixture()
def page(monkeypatch):
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    from gui.tabs.biglietti_tab import BigliettiTab
    import logging
    tab = BigliettiTab(root, {}, lambda **kw: None, logging.getLogger("test"))
    tab.pack()
    show_parent = ttk.Frame(root)
    tab.attach_show_orders_page(show_parent, lambda: None)
    warnings, redirects = [], []
    monkeypatch.setattr("gui.tabs.biglietti_tab.messagebox.showwarning", lambda title, msg, **k: warnings.append((title, msg)))
    tab._goto_show_orders = lambda: redirects.append(True)
    yield SimpleNamespace(root=root, tab=tab, warnings=warnings, redirects=redirects)
    root.destroy()


def test_the_page_has_one_tab_per_customer_and_a_separate_shared_orders_page(page):
    book = page.tab._client_page_book
    assert [book.tab(t, "text").strip() for t in book.tabs()] == ["ELVY", "MED", "EL KAMAL"]
    assert len(page.tab._convert_buttons) == 3 and len(page.tab._status_labels) == 3
    assert page.tab.shared_excel_label is page.tab._show_orders_page.path_label


def test_every_page_shows_the_folder_and_the_status(page, tmp_path):
    """The Filato folder row exists on all three pages, and so does the status line."""
    folder = tmp_path / "filato"
    folder.mkdir()
    page.tab._set_dir_label("filato", str(folder))
    assert len(page.tab._dir_labels["filato"]) == 3
    assert {str(label.cget("text")) for label in page.tab._dir_labels["filato"]} == {str(folder)}
    page.tab._set_status("Completed — done")
    page.root.update()
    assert {str(label.cget("text")) for label in page.tab._status_labels} == {"✔ Completed — done"}


@pytest.mark.parametrize("customer", ["ELVY", "MED"])
def test_converting_without_a_show_orders_file_warns_and_opens_that_page(page, customer):
    page.tab.shared_excel_path = None
    page.tab._on_client_convert(customer)
    assert [title for title, _ in page.warnings] == ["Missing Show Orders file"]
    assert page.redirects == [True]
    assert all(button._state != "disabled" for button in page.tab._convert_buttons)   # nothing started


def test_kamal_does_not_need_the_show_orders_file(page):
    page.tab.shared_excel_path = None
    page.tab._on_client_convert("EL_KAMAL")
    assert [title for title, _ in page.warnings] == ["Missing Input"]            # it asks for the order data instead
    assert page.redirects == []


def test_a_new_workbook_that_is_not_created_yet_counts_as_chosen(page, tmp_path):
    """"Create New" only picks the place; the file is written by the first conversion."""
    page.tab._set_shared_excel(tmp_path / "Create Orders.xlsx")
    assert not (tmp_path / "Create Orders.xlsx").exists()
    assert page.tab._ensure_show_orders_file("ELVY") is True and page.warnings == []
    assert str(tmp_path / "Create Orders.xlsx") in page.tab._show_orders_page.path_label.cget("text")


def test_printing_from_show_orders_can_disable_every_convert_button(page):
    """_print_selected_shared used the old single Convert button, which no longer exists."""
    page.tab._set_convert_buttons_state("disabled")
    assert all(button._state == "disabled" for button in page.tab._convert_buttons)
    page.tab._set_convert_buttons_state("normal")
    assert not hasattr(page.tab, "convert_btn")


class _SyncThread:
    """Runs the worker right away on the calling thread: Tk only accepts after() calls from
    other threads while a real mainloop is running, which a test does not have."""

    def __init__(self, target, args=(), daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def test_a_conversion_runs_for_one_customer_and_reports_back(page, dump, tmp_path, monkeypatch):
    monkeypatch.setattr("gui.tabs.biglietti_tab.threading.Thread", _SyncThread)
    page.tab.data_path = dump
    page.tab.template_path = _template(tmp_path / "Biglietti.docx")
    page.tab.elvy_output_dir = tmp_path / "elvy_out"
    page.tab.elvy_output_dir.mkdir()
    page.tab._set_shared_excel(tmp_path / "Show Orders.xlsx")          # a new workbook: not created yet
    infos = []
    monkeypatch.setattr("gui.tabs.biglietti_tab.messagebox.showinfo", lambda title, msg, **k: infos.append(title))
    page.tab._on_client_convert("ELVY")
    for _ in range(20):
        page.root.update()
        time.sleep(0.02)
    assert infos == ["ELVY — Conversion Complete"]
    assert (tmp_path / "elvy_out" / "PO-1500 & 1501-2026.xlsx").is_file()
    assert (tmp_path / "Show Orders.xlsx").is_file()
    assert all(button._state == "normal" for button in page.tab._convert_buttons)
