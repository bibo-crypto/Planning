"""كتابة إكسل العميل (ELVY/MED/EL_KAMAL) وملف الفيلاتو + ربط الأعمدة بالبيليتو.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Collection, Mapping

from openpyxl import Workbook

from exporters.biglietti.enrichment import _filato_rows
from exporters.biglietti.fields import _number, _polmoni_segment
from exporters.biglietti.records import OrderRecord
from exporters.biglietti.workbook_io import style_sheet
from utility.column_selection import pick_headers, pick_values, visible_positions
from utility.excel_io import safe_save_workbook

COMMON_HEADERS = [
    "Dispo/Riga", "Articolo", "Titolo", "Formato", "Ordine", "Codice", "Colore", "Rocche", "KG",
    "M/C", "Partita Col", "Consegna", "Commento", "Bagno", "Cliente", "Partita GG",
]
EXTRA_HEADERS = ["Color Tube", "VMM22", "Prezzo", "Densita` (360-390)"]
FILATO_HEADERS = ["Articolo", "Titolo", "Partita", "Rocche", "Peso", "تحضير خام"]

# What each Word ticket prints, as (row, cell) of the template table -> the Excel column it
# shows.  Switching a column off in the column picker leaves the matching cell empty.
TICKET_CELL_COLUMNS: dict[tuple[int, int], str] = {
    (2, 2): "Titolo", (2, 3): "Formato", (2, 4): "Articolo",
    (3, 2): "Partita GG", (4, 2): "Colore", (5, 2): "Partita Col",
    (6, 2): "Dispo/Riga", (6, 3): "Ordine", (7, 3): "Bagno",
    (8, 2): "Rocche", (9, 2): "KG", (10, 2): "M/C", (11, 3): "VMM22",
}
# The columns that make up the first line of a ticket, per customer (see _ticket_header).
TICKET_HEADER_COLUMNS: dict[str, tuple[str, ...]] = {
    "ELVY": ("Cliente", "Commento"),
    "MED": ("Cliente", "Commento", "POLMON", "Cliente MED"),
    "EL_KAMAL": ("Cliente", "Consegna"),
}
# Customer code -> sheet name, to find the Excel columns a ticket may print.
CUSTOMER_BY_CODE: dict[str, str] = {"3009": "ELVY", "3004": "MED", "3019": "EL_KAMAL"}


def customer_headers(customer: str) -> list[str]:
    """The headers of one customer's sheet: ELVY, MED or EL_KAMAL (Kamal has no extra columns)."""
    if customer == "MED":
        return COMMON_HEADERS + ["Partita MED", "Cliente MED", "POLMON"] + EXTRA_HEADERS
    if customer == "EL_KAMAL":
        return list(COMMON_HEADERS)
    return COMMON_HEADERS + ["Delivery Date"] + EXTRA_HEADERS


def ticket_columns(customer: str) -> list[str]:
    """The labels (column names) a customer's Word ticket prints, in the picker's order."""
    printed = set(TICKET_CELL_COLUMNS.values()) | set(TICKET_HEADER_COLUMNS.get(customer, ()))
    return [label for label in customer_headers(customer) if label in printed]


def ticket_hidden_labels(customer_code: str, hidden: Collection[str] = ()) -> frozenset[str]:
    """Labels a ticket must leave empty: the ones switched off, plus every ticket field
    whose column the customer's Excel sheet does not have (e.g. VMM22 for EL KAMAL)."""
    customer = CUSTOMER_BY_CODE.get(customer_code)
    if customer is None:
        return frozenset(hidden)
    sheet_columns = set(customer_headers(customer))
    printable = set(TICKET_CELL_COLUMNS.values()) | set(TICKET_HEADER_COLUMNS.get(customer, ()))
    return frozenset(hidden) | {label for label in printable if label not in sheet_columns}


def export_workbook(
    path: Path,
    records: list[OrderRecord],
    raw_rows: list[dict[str, Any]],
    include_filato: bool = True,
    stem: str = "",
    customer: str = "",
    magazino_summary=None,
    hide_kamal_quantities: bool = False,
    hidden_columns: Mapping[str, Collection[str]] | None = None,
) -> None:
    """Write the "Create (EXCEL+Biglietti)" workbook for one customer.

    Records are sorted numerically by Partita Col (empty ones last).  Writes the
    common columns plus the customer extras (Color Tube, VMM22, Prezzo, Densita),
    the optional filato (yarn) section, and styles the sheet.
    hide_kamal_quantities (EL KAMAL only) leaves the Rocche and KG cells empty.
    The EL KAMAL sheet has no VMM22 column.
    hidden_columns ({sheet title: labels}) leaves out the columns the planner switched off
    in the column picker -- the customer's sheet is named after the customer, the raw-yarn
    sheet "Filato x Tinturia".  Nothing hidden (the default) writes every column.
    """
    customer = customer or ("ELVY" if records[0].customer_code == "3009" else "MED")
    hidden_columns = hidden_columns or {}
    # The Create (EXCEL+Biglietti) extract is consumed in Partita Col order.
    # Sort numerically (not lexicographically, so 20 comes after 3) and keep
    # rows with an empty/non-numeric Partita Col at the end.
    records = sorted(
        records,
        key=lambda record: (
            _number(record.colored_batch) is None,
            _number(record.colored_batch) if _number(record.colored_batch) is not None else 0,
        ),
    )
    wb = Workbook()
    ws = wb.active
    ws.title = customer
    headers = customer_headers(customer)
    shown = visible_positions(headers, hidden_columns.get(customer))
    ws.append(pick_headers(headers, hidden_columns.get(customer)))
    for r in records:
        quantity = None if customer == "EL_KAMAL" and hide_kamal_quantities else r.quantity_cones
        kg = None if customer == "EL_KAMAL" and hide_kamal_quantities else r.kg
        row = [r.dispo, r.article, r.title, r.formato, r.order_no, r.color_code, r.color_name,
               quantity, kg, r.machine, r.colored_batch, r.delivery,
               r.commento, r.bagno, r.customer_name, r.raw_batch]
        if customer == "MED":
            polmon = _polmoni_segment(r.additional_raw)
            row += [r.partita_med, r.cliente_med, polmon, r.color_tube, r.vmm22, r.prezzo, r.densita]
        elif customer == "EL_KAMAL":
            pass                                  # nothing beyond the common columns
        else:
            row += [r.delivery_date, r.color_tube, r.vmm22, r.prezzo, r.densita]
        ws.append(pick_values(row, shown))
    if include_filato:
        fws = wb.create_sheet("Filato x Tinturia")
        filato_hidden = hidden_columns.get("Filato x Tinturia")
        fheaders = pick_headers(FILATO_HEADERS, filato_hidden)
        fws.append(fheaders)
        for r in _filato_rows(records, raw_rows, magazino_summary):
            fws.append([r[h] for h in fheaders])
        style_sheet(fws)
    style_sheet(
        ws,
        date_columns=("Consegna", "Delivery Date"),
        duplicate_highlight_columns=("Bagno",),
        range_highlight_columns={"Densita` (360-390)": (360, 390)},
        days_until_highlight_columns={"Delivery Date": 4},
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_save_workbook(wb, path, keep_backup=False)
    wb.close()


def export_filato_workbook(
    path: Path,
    records: list["OrderRecord"],
    raw_rows: list[dict[str, Any]],
    magazino_summary=None,
) -> None:
    """Export only the optional ``Filato x Tinturia`` workbook."""
    wb = Workbook()
    ws = wb.active
    ws.title = "Filato x Tinturia"
    headers = ["Articolo", "Titolo", "Partita", "Rocche", "Peso", "تحضير خام"]
    ws.append(headers)
    for r in _filato_rows(records, raw_rows, magazino_summary):
        ws.append([r[h] for h in headers])
    style_sheet(ws)
    path.parent.mkdir(parents=True, exist_ok=True)
    safe_save_workbook(wb, path)
    wb.close()
