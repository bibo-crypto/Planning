"""Prezzi-PO: the price-check file written next to an Ordine Elvy workbook.

Same sheet as Ordine MED's Prezzi (columns and styling live in
exporters.prezzi_workbook); this module only turns Purchase Order lines into those
rows and names the file after the PO.
"""
from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Mapping

from exporters.biglietti_exporter import apply_machine_surcharge
from exporters.prezzi_workbook import price_cell, write_prezzi_workbook
from parsers.dfm_lookup import raw_to_finished_articolo
from parsers.pdf_parser import OrderRow
from pipelines.ordini_elvy import RE_ABBINA_CONES, _to_c_code
from utility.utils import clean_text, logger

_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]')


def machine_capacity(abbina: str) -> int | None:
    """The M/C of a line: the machine capacity in cones named by its Abbina
    ("Machine 72 Cones" -> 72); None when the Abbina names none."""
    match = RE_ABBINA_CONES.search(clean_text(abbina))
    return int(match.group(1)) if match else None


def po_label(rows: list[OrderRow]) -> str:
    """The PO number(s) of the lines, from their POD No column: "1500", or "1500 & 1501"
    when the lines belong to several POs.  Empty when no line has one."""
    numbers: list[str] = []
    for row in rows:
        number = re.sub(r"^PO[-\s]*", "", clean_text(row.pod_no), flags=re.IGNORECASE)
        number = _INVALID_FILENAME_CHARS.sub("_", number).strip(" .")
        if number and number not in numbers:
            numbers.append(number)
    return " & ".join(numbers)


def prezzi_rows(rows: list[OrderRow], titolo_by_articolo: Mapping[str, str] | None = None) -> list[list[Any]]:
    """One Prezzi line per PO line, in PREZZI_HEADERS order.

    ARTICOLO is the finished (dyed) article the price list is keyed on; TITOLO comes
    from the DFM reference (falling back to the PDF's Ne); M/C is the machine capacity
    of the line's Abbina, and the last column is Prezzo + 2$ for the machines that
    carry that surcharge (the same rule as Ordine MED and Situazione).
    """
    titles = titolo_by_articolo or {}
    out: list[list[Any]] = []
    for index, row in enumerate(rows, start=1):
        finished = raw_to_finished_articolo(row.articolo_delta) or _to_c_code(row.articolo_delta) or clean_text(row.articolo_delta)
        titolo = titles.get(finished) or titles.get(clean_text(row.articolo_delta)) or clean_text(row.ne)
        mc = machine_capacity(row.abbina)
        prezzo = row.prezzo
        out.append([
            row.pos if row.pos is not None else index,
            finished,
            titolo,
            row.coloredfm,
            row.quantity_cones,
            clean_text(row.cldescr) or clean_text(row.colour),
            row.livello,
            mc,
            price_cell(prezzo),
            price_cell(apply_machine_surcharge(prezzo, mc)),
        ])
    return out


def export_prezzi_po(folder: Path, rows: list[OrderRow], titolo_by_articolo: Mapping[str, str] | None = None) -> Path | None:
    """Write ``Prezzi-PO-<PO number(s)>.xlsx`` in ``folder``; None when there are no lines.

    Without any POD No the file is called plain ``Prezzi-PO.xlsx``."""
    if not rows:
        return None
    label = po_label(rows)
    path = folder / (f"Prezzi-PO-{label}.xlsx" if label else "Prezzi-PO.xlsx")
    write_prezzi_workbook(path, prezzi_rows(rows, titolo_by_articolo), sheet_title="ELVY")
    logger.info("Saved: %s", path.name)
    return path
