"""The pages whose output columns can be chosen, and the columns of each of their sheets.

Single responsibility: describe WHAT can be chosen.  The labels are read from the
exporters' own column tables, so the picker can never list a column the file does not
have (or miss one that was added later).  Storing and applying the choice is
utility/column_selection.py; showing it is gui/column_picker.py.

Files that feed the ERP (EXCEL PER ORDINE VENDITA EGITTO.xlsx, Filato x Tinturia.xlsx,
and the shared Create Orders workbook) keep their fixed layout and are not listed: a
missing column there would break the import on the other side.
"""
from __future__ import annotations

from dataclasses import dataclass

from utility.column_selection import BIGLIETTI_SHEET_NAMES


@dataclass(frozen=True)
class SheetSpec:
    """One sheet: its title (also the key of the saved choice) and its column labels in file order."""
    title: str
    labels: tuple[str, ...]
    # Labels that print on the Word ticket (Biglietti pages): marked in the picker.
    ticket: frozenset[str] = frozenset()
    note: str = ""


@dataclass(frozen=True)
class PageSpec:
    """One page: its key, its name in the dialog title and the sheets it can write."""
    key: str
    title: str
    sheets: tuple[SheetSpec, ...]
    note: str = ""


PAGE_KEYS = (
    "ordine_elvy", "ordine_kamal", "ordine_med",
    "biglietti_elvy", "biglietti_med", "biglietti_el_kamal",
)

_PREZZI_NOTE = "Prezzi: the price-check file written next to the order workbook."


def _labels(columns) -> tuple[str, ...]:
    """Labels of excel_exporter-style (label, attribute, type) column definitions."""
    return tuple(label for label, _attr, _kind in columns)


def _ordine_elvy() -> PageSpec:
    from exporters.excel_exporter import COLUMNS, FILATO_TINTURIA_COLUMNS, ORDINI_ELVY_COLUMNS
    from exporters.prezzi_workbook import PREZZI_HEADERS
    return PageSpec("ordine_elvy", "Ordine Elvy", (
        SheetSpec("Purchase Orders", _labels(COLUMNS)),
        SheetSpec("Ordini ELVY", _labels(ORDINI_ELVY_COLUMNS)),
        SheetSpec("Filato x Tinturia", _labels(FILATO_TINTURIA_COLUMNS)),
        SheetSpec("Prezzi", tuple(PREZZI_HEADERS), note=_PREZZI_NOTE),
    ), note="The ERP files (EXCEL PER ORDINE VENDITA EGITTO / Filato x Tinturia) are not affected.")


def _ordine_kamal() -> PageSpec:
    from exporters.excel_exporter import FILATO_TINTURIA_COLUMNS
    from exporters.kamal_excel_exporter import ORDINE_KAMAL_COLUMNS, RAW_KAMAL_COLUMNS
    return PageSpec("ordine_kamal", "Ordine Kamal", (
        SheetSpec("Kamal Order", _labels(RAW_KAMAL_COLUMNS)),
        SheetSpec("Ordine Kamal", _labels(ORDINE_KAMAL_COLUMNS)),
        SheetSpec("Filato x Tinturia", _labels(FILATO_TINTURIA_COLUMNS)),
    ), note="The ERP files (EXCEL PER ORDINE VENDITA EGITTO / Filato x Tinturia) are not affected.")


def _ordine_med() -> PageSpec:
    from exporters.prezzi_workbook import PREZZI_HEADERS
    from pipelines.ordine_med import FILATO_AVAILABILITY_HEADERS, ORDINE_DA_CREARE_HEADERS, SYSTEM_IMPORT_HEADERS
    return PageSpec("ordine_med", "Ordine Med", (
        SheetSpec("Ordine da creare", tuple(ORDINE_DA_CREARE_HEADERS)),
        SheetSpec("Dati sistema (B-N)", tuple(SYSTEM_IMPORT_HEADERS),
                  note="This sheet is laid out for the system import: leave out columns with care."),
        SheetSpec("Filato X Tinturia", tuple(FILATO_AVAILABILITY_HEADERS)),
        SheetSpec("Prezzi", tuple(PREZZI_HEADERS), note=_PREZZI_NOTE),
    ), note="The ERP files (Ordine_MED_ERP / Filato X Tinturia) are not affected.")


def _biglietti(key: str, title: str) -> PageSpec:
    from exporters.biglietti_exporter import (
        FILATO_HEADERS, customer_headers, ticket_columns,
    )
    customer = BIGLIETTI_SHEET_NAMES[key]
    return PageSpec(key, title, (
        SheetSpec(
            customer, tuple(customer_headers(customer)),
            ticket=frozenset(ticket_columns(customer)),
            note="Columns marked 🖨 are printed on the Word ticket: a column that is off leaves its place on the ticket empty.",
        ),
        SheetSpec("Filato x Tinturia", tuple(FILATO_HEADERS)),
    ), note="The shared Create Orders workbook and the Filato file for the ERP are not affected.")


_BUILDERS = {
    "ordine_elvy": _ordine_elvy,
    "ordine_kamal": _ordine_kamal,
    "ordine_med": _ordine_med,
    "biglietti_elvy": lambda: _biglietti("biglietti_elvy", "Biglietti — ELVY"),
    "biglietti_med": lambda: _biglietti("biglietti_med", "Biglietti — MED"),
    "biglietti_el_kamal": lambda: _biglietti("biglietti_el_kamal", "Biglietti — EL KAMAL"),
}


# What breaks elsewhere when a column is switched off: page -> sheet -> label -> consequence.
_KAMAL_FEEDS_BIGLIETTI = "Biglietti (EL KAMAL) reads this column straight from the Ordine Kamal workbook: without it the ticket and its Excel lose this value."
_ORDINE_KAMAL_DEPENDENTS = (
    "CLIENTE", "ARTICOLO", "COLORE", "Q.TA", "CONSEGNA", "COMMENTO", "SIGLA DISPOSIZIONE",
    "BAGNO PREPOSTO", "GRUPPO MACCHINA",
)
DEPENDENCIES: dict[str, dict[str, dict[str, str]]] = {
    "ordine_kamal": {
        "Ordine Kamal": {label: _KAMAL_FEEDS_BIGLIETTI for label in _ORDINE_KAMAL_DEPENDENTS},
        "Kamal Order": {
            "COLOREDFM": "Biglietti (EL KAMAL) looks the colour name up through this column.",
            "Colore": "Biglietti (EL KAMAL) takes the long colour name from this column.",
        },
        "Filato x Tinturia": {
            "Partita": "Biglietti (EL KAMAL) matches the raw-yarn batch (Partita GG / KG) through this column.",
        },
    },
}
_BIGLIETTI_HIGHLIGHTS = {
    "Bagno": "the duplicate-Bagno highlight is lost.",
    "Delivery Date": "the \"delivery within 4 days\" highlight is lost.",
    "Densita` (360-390)": "the out-of-range (360-390) highlight is lost.",
}


def dependency_notes(key: str) -> dict[str, dict[str, str]]:
    """{sheet: {label: what is lost}} for the columns another page or a highlight relies on.

    Biglietti sheets add two automatic notes: the Word ticket cell left empty, and the
    conditional highlight that needs the column."""
    notes = {sheet: dict(labels) for sheet, labels in DEPENDENCIES.get(key, {}).items()}
    if key in BIGLIETTI_SHEET_NAMES:
        spec = page_spec(key)
        sheet = spec.sheets[0]
        entry = notes.setdefault(sheet.title, {})
        for label in sheet.labels:
            parts = []
            if label in sheet.ticket:
                parts.append("its place on the Word ticket stays empty")
            if label in _BIGLIETTI_HIGHLIGHTS:
                parts.append(_BIGLIETTI_HIGHLIGHTS[label])
            if parts:
                entry[label] = "; ".join(parts).rstrip(".") + "."
    return notes


def page_spec(key: str) -> PageSpec:
    """The PageSpec of ``key`` (one of PAGE_KEYS); the exporter modules are imported on first use."""
    try:
        return _BUILDERS[key]()
    except KeyError:
        raise ValueError(f"Unknown column page: {key!r}") from None
