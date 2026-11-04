"""كتابة بيليتو الوورد (جدول لكل لون) وسطر العنوان.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any, Collection, Mapping

from exporters.biglietti.excel_writer import TICKET_CELL_COLUMNS, ticket_hidden_labels
from exporters.biglietti.fields import _clean, _number, _polmoni_segment
from exporters.biglietti.records import OrderRecord


def export_word(
    path: Path,
    template_path: Path,
    records: list[OrderRecord],
    stem: str = "",
    hide_kamal_quantities: bool = False,
    hidden_columns: Mapping[str, Collection[str]] | None = None,
) -> None:
    """Create one Word file, one Biglietto page per order color.

    hidden_columns ({customer code: labels}) are the columns switched off in the column
    picker: the ticket cell that would print such a column is left empty (see
    TICKET_CELL_COLUMNS).  Nothing hidden (the default) prints the whole ticket.

    Uses python-docx (lxml-backed) instead of the stdlib ElementTree, and
    deep-copies the template's own table element rather than re-parsing a
    serialized copy. Both changes avoid the namespace-prefix rewriting that
    xml.etree.ElementTree does on round-trip, which is the most likely
    cause of Word's "unreadable content" repair prompt on the old output.
    """
    from docx import Document
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn
    from docx.shared import Inches

    # Keep the ticket pages in the same numeric Partita Col order as the
    # extracted Excel sheet.  MED source rows are not always delivered in
    # that order, so sorting only the workbook is not enough.
    records = sorted(
        records,
        key=lambda record: (
            _number(record.colored_batch) is None,
            _number(record.colored_batch) if _number(record.colored_batch) is not None else 0,
        ),
    )

    doc = Document(str(template_path))
    if not doc.tables:
        raise ValueError("Il modello Biglietti non contiene la tabella prevista.")

    # The template's own page margins (1in top/bottom) leave the ticket
    # table only ~0.05in of headroom before it spills its last 2-3 rows
    # onto a second page whenever a bilingual label wraps to 2 lines --
    # that's the "biglietto finishes outside its own page" issue. Trimming
    # the margins buys back room without touching row heights or fonts.
    for sect in doc.sections:
        sect.top_margin = Inches(0.5)
        sect.bottom_margin = Inches(0.5)

    template_tbl = doc.tables[0]._tbl
    body = doc.element.body
    template_tbl.getparent().remove(template_tbl)
    sect_pr = body.find(qn("w:sectPr"))

    def _insert(el) -> None:
        if sect_pr is not None:
            sect_pr.addprevious(el)
        else:
            body.append(el)

    for idx, record in enumerate(records):
        new_tbl = copy.deepcopy(template_tbl)
        hidden = ticket_hidden_labels(record.customer_code, (hidden_columns or {}).get(record.customer_code, ()))
        _fill_ticket_table(new_tbl, record, qn, OxmlElement, stem, hide_kamal_quantities, hidden)
        for row in new_tbl.findall(qn("w:tr")):
            cant_split = OxmlElement("w:cantSplit")
            row.get_or_add_trPr().append(cant_split)
        _insert(new_tbl)
        if idx != len(records) - 1:
            p = OxmlElement("w:p")
            r = OxmlElement("w:r")
            br = OxmlElement("w:br")
            br.set(qn("w:type"), "page")
            r.append(br)
            p.append(r)
            _insert(p)

    path.parent.mkdir(parents=True, exist_ok=True)
    doc.save(str(path))


def _fill_ticket_table(
    tbl, r: OrderRecord, qn, OxmlElement, stem: str, hide_kamal_quantities: bool = False,
    hidden: Collection[str] = (),
) -> None:
    """Fill one ticket (a Word table of the Biglietti template) with an order record.

    Works on the raw WordprocessingML: each put(row, cell, text) clears the cell's
    runs, writes the text into the first run and applies the template's font size.
    hide_kamal_quantities leaves the quantity/kg cells empty for EL KAMAL (customer 3019) tickets.
    hidden: the column labels switched off -- their cells are written empty.
    """
    rows = tbl.findall(qn("w:tr"))

    def put(row: int, cell: int, text: Any) -> None:
        """Write text into cell number `cell` of row number `row` (both 1-based) of the ticket table: clears the cell's runs, writes the text into the first run and applies the template's font size."""
        c = rows[row - 1].findall(qn("w:tc"))[cell - 1]
        for p in c.findall(".//" + qn("w:p")):
            for t in p.findall(".//" + qn("w:t")):
                t.text = ""
            first = p.find(".//" + qn("w:t"))
            if first is None:
                run = OxmlElement("w:r")
                first = OxmlElement("w:t")
                run.append(first)
                p.append(run)
            first.text = _clean(text)
            for run in p.findall(".//" + qn("w:r")):
                r_pr = run.find(qn("w:rPr"))
                if r_pr is None:
                    r_pr = OxmlElement("w:rPr")
                    run.insert(0, r_pr)
                size = r_pr.find(qn("w:sz"))
                if size is None:
                    size = OxmlElement("w:sz")
                    r_pr.append(size)
                size.set(qn("w:val"), "28")
            break

    def show(row: int, cell: int, text: Any) -> None:
        """put() the text, or an empty cell when the column this cell prints is switched off."""
        label = TICKET_CELL_COLUMNS.get((row, cell))
        put(row, cell, "" if label in hidden else text)

    put(1, 2, _ticket_header(r, stem, hidden))
    show(2, 2, r.title); show(2, 3, r.formato); show(2, 4, r.article)
    show(3, 2, r.raw_batch); show(4, 2, r.color_name); show(5, 2, r.colored_batch)
    show(6, 2, r.dispo); show(6, 3, f"Ordine.  {r.order_no}"); show(7, 3, r.bagno)
    ticket_quantity = None if r.customer_code == "3019" and hide_kamal_quantities else r.quantity_cones
    ticket_kg = None if r.customer_code == "3019" and hide_kamal_quantities else r.kg
    show(8, 2, ticket_quantity); show(9, 2, ticket_kg); show(10, 2, r.machine)
    vmm = r.vmm22 if r.vmm22 is not None else r.raw_weight
    show(11, 3, f"VMM22( {float(vmm):.2f} )Kg" if vmm is not None else "VMM22(       )Kg")


def _format_date(value: Any) -> str:
    try:
        return value.strftime("%d/%m/%Y")
    except AttributeError:
        return _clean(value)


def _ticket_header(r: OrderRecord, stem: str, hidden: Collection[str] = ()) -> str:
    """Top line of the ticket. Differs per customer:
    - MED: first 3 letters of Cliente - Commento - Polmon - Cliente MED
      (blank segments dropped rather than left as bare dashes).
    - EL KAMAL: Cliente - Consegna.
    - Everything else (ELVY): Cliente - Commento.  The header is per ticket,
      so it must never inherit a batch/file suffix such as ``PG-X``.
    A part whose column is in ``hidden`` (switched off in the column picker) is left out."""
    def keep(label: str, text: str) -> str:
        return "" if label in hidden else text

    if r.customer_code == "3004":  # MED
        polmon = _polmoni_segment(r.additional_raw)
        parts = [keep("Cliente", r.customer_name[:3]), keep("Commento", r.commento),
                 keep("POLMON", polmon), keep("Cliente MED", r.cliente_med)]
        return "-".join(p for p in parts if p)
    if r.customer_code == "3019":  # EL KAMAL
        if not ({"Cliente", "Consegna"} & set(hidden)):
            return f"{r.customer_name} - {_format_date(r.delivery)}"
        parts = [keep("Cliente", r.customer_name), keep("Consegna", _format_date(r.delivery))]
        return " - ".join(p for p in parts if p)
    parts = [keep("Cliente", r.customer_name), keep("Commento", r.commento)]
    return "-".join(part for part in parts if part)
