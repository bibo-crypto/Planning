"""Column picker feature: storage, Excel sheets and Word tickets honour the switched-off columns."""
import openpyxl
import pytest
from docx import Document

from exporters.biglietti_exporter import OrderRecord, export_word, export_workbook
from pipelines import ordine_med
from utility import column_selection as cs


@pytest.fixture(autouse=True)
def _settings_file(tmp_path, monkeypatch):
    monkeypatch.setattr(cs, "COLUMN_SELECTION_FILE", tmp_path / "column_selection.json")


def _record(code="3004", name="MED"):
    return OrderRecord(
        customer_code=code, customer_name=name, article="C010937S", description="", additional_raw="",
        color_code="343", color_name="Blue", order_no="7", order_row="1", colored_batch="159527",
        raw_batch="159233", quantity_cones=72, raw_weight=50.0, dispo="D-1", bagno="T99",
        delivery="20/10/2026", machine="3", title="50/1", commento="PG-1", kg=50.0,
    )


def _template(path):
    doc = Document()
    table = doc.add_table(rows=12, cols=5)
    for r in range(12):
        table.cell(r, 0).text = f"label{r}"
    doc.save(path)


def test_storage_roundtrip_reset_and_never_empty():
    assert cs.load_hidden("ordine_med") == {}
    cs.save_hidden("ordine_med", {"Prezzi": ["COLORE"], "Ordine da creare": []})
    assert cs.load_hidden("ordine_med") == {"Prezzi": frozenset({"COLORE"})}
    cs.reset("ordine_med")
    assert cs.load_hidden("ordine_med") == {}
    assert cs.visible_positions(["a", "b"], {"a", "b"}) == [0, 1]   # all hidden -> keep all
    assert cs.visible_positions(["a", "b"], {"a"}) == [1]


def test_biglietti_excel_and_filato_sheets_drop_hidden_columns(tmp_path):
    path = tmp_path / "out.xlsx"
    export_workbook(path, [_record()], [], customer="MED",
                    hidden_columns={"MED": {"Bagno", "KG"}, "Filato x Tinturia": {"Peso"}})
    wb = openpyxl.load_workbook(path)
    header = [c.value for c in wb["MED"][1]]
    assert "Bagno" not in header and "KG" not in header and "Articolo" in header
    assert "Peso" not in [c.value for c in wb["Filato x Tinturia"][1]]


def test_word_ticket_leaves_hidden_columns_empty(tmp_path):
    tpl, out = tmp_path / "t.docx", tmp_path / "o.docx"
    _template(tpl)
    export_word(out, tpl, [_record()], hidden_columns={"3004": {"Bagno", "Colore"}})
    text = "\n".join(c.text for t in Document(out).tables for row in t.rows for c in row.cells)
    assert "T99" not in text and "Blue" not in text
    assert "50/1" in text and "C010937S" in text


def test_med_workbook_and_prezzi_drop_hidden_columns(tmp_path):
    path = tmp_path / "med.xlsx"
    hidden = {"Ordine da creare": {ordine_med.ORDINE_DA_CREARE_HEADERS[1]},
              "Dati sistema (B-N)": {ordine_med.SYSTEM_IMPORT_HEADERS[0]},
              "Filato X Tinturia": {"Disponibilita'"}}
    ordine_med.export_ordine_med_workbook(path, [], [], hidden_columns=hidden)
    wb = openpyxl.load_workbook(path)
    assert ordine_med.ORDINE_DA_CREARE_HEADERS[1] not in [c.value for c in wb["Ordine da creare"][1]]
    assert ordine_med.SYSTEM_IMPORT_HEADERS[0] not in [c.value for c in wb["Dati sistema (B-N)"][1]]
    assert "Disponibilita'" not in [c.value for c in wb["Filato X Tinturia"][1]]
    ordine_med.export_prezzi_workbook(tmp_path / "p.xlsx", [], hidden_columns={"COLORE"})
    assert "COLORE" not in [c.value for c in openpyxl.load_workbook(tmp_path / "p.xlsx").active[1]]


def test_order_is_applied_and_unknown_labels_follow():
    choice = cs.SheetChoice({"b"}, ["d", "c", "a"])
    assert cs.visible_positions(["a", "b", "c", "d", "e"], choice) == [3, 2, 0, 4]


def test_excel_follows_the_dragged_order(tmp_path):
    path = tmp_path / "o.xlsx"
    order = ["Titolo", "Articolo"]
    export_workbook(path, [_record()], [], customer="MED",
                    hidden_columns={"MED": cs.SheetChoice({"Bagno"}, order)})
    header = [c.value for c in openpyxl.load_workbook(path)["MED"][1]]
    assert header[:2] == ["Titolo", "Articolo"] and "Bagno" not in header


def test_kamal_ticket_has_no_vmm22_because_its_excel_has_none(tmp_path):
    tpl, out = tmp_path / "t.docx", tmp_path / "o.docx"
    _template(tpl)
    record = _record("3019", "EL KAMAL")
    record.vmm22 = 49.25
    export_word(out, tpl, [record])
    text = "\n".join(c.text for t in Document(out).tables for row in t.rows for c in row.cells)
    assert "VMM22" not in text and "49.25" not in text


def test_dependency_notes_cover_kamal_feed_and_tickets():
    from exporters.column_catalog import dependency_notes
    assert "ARTICOLO" in dependency_notes("ordine_kamal")["Ordine Kamal"]
    assert "Word ticket" in dependency_notes("biglietti_med")["MED"]["Bagno"]


def test_picker_dialog_saves_unticked_columns_and_order(monkeypatch):
    tk = pytest.importorskip("tkinter")
    from tkinter import messagebox
    from gui.column_picker import open_column_picker
    try:
        root = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    asked = []
    monkeypatch.setattr(messagebox, "askyesno", lambda *a, **k: asked.append(a[1]) or True)
    dialog = open_column_picker(root, "biglietti_med")
    dialog.set_tick("MED", "Bagno", False)
    tree = dialog._trees["MED"]
    tree.move(tree.get_children("")[-1], "", 0)               # last column dragged to the top
    dialog._save()
    saved = cs.load_hidden("biglietti_med")["MED"]
    assert saved == frozenset({"Bagno"}) and saved.order[0] == "Densita` (360-390)"
    assert asked and "Bagno" in asked[0]                      # the Word-ticket warning was shown
    root.destroy()
