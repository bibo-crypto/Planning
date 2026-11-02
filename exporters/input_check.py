"""Look at an input workbook BEFORE converting and name what is missing.

Single responsibility: report the columns/sheets a conversion needs and the file does not
have, so the planner learns it in one message instead of from a half-empty result.  It only
reads the first rows of each sheet and never raises: a file it cannot open is left to the
conversion's own error message.  The header spellings are those the readers accept
(biglietti_exporter.HEADER_ALIASES), so a file that converts fine never gets a warning.
"""
from __future__ import annotations

from itertools import islice
from pathlib import Path
from typing import Any, Iterable, Sequence

import openpyxl

from exporters.biglietti_exporter import HEADER_ALIASES, _key, _read_sheet_rows

HEAD_ROWS = 12            # the readers look for the header row in the first 12 rows

# Each entry is one needed column; a tuple lists spellings that are equally good.
ERP_ORDER_COLUMNS: tuple[str | tuple[str, ...], ...] = (
    "Cliente", "Articolo", "Colore", "Ordine", "Riga", "Partita",
    ("Ordinata", "Assegnata"), "Consegna", "Descrizione aggiuntiva ordine",
)
DISPO_COLUMNS: tuple[str | tuple[str, ...], ...] = ("Dispo", ("Field2", "Bagno"))
KAMAL_ORDER_COLUMNS: tuple[str | tuple[str, ...], ...] = (
    "ARTICOLO", "COLORE", "Q.TA", "COMMENTO", "CONSEGNA", "BAGNO PREPOSTO", "GRUPPO MACCHINA",
)
KAMAL_NAME_COLUMNS: tuple[str | tuple[str, ...], ...] = ("COLOREDFM", "Colore")
MED_ORDER_COLUMNS: tuple[str | tuple[str, ...], ...] = (
    "ARTICOLO", "TITOLO", "DESCR COL", "COLORE", "ROCC", "ABBIN", "CONSEGNA", "PT GRG",
)


class _Head:
    """The first rows of a sheet, shaped like the worksheet _read_sheet_rows expects."""
    def __init__(self, ws) -> None:
        self._ws = ws

    def iter_rows(self, values_only: bool = True) -> Iterable[Any]:
        return islice(self._ws.iter_rows(values_only=values_only), HEAD_ROWS)


def _headers(ws) -> set[str] | None:
    """The header names (normalised) of a sheet, or None when it has no readable rows."""
    rows = _read_sheet_rows(_Head(ws))
    return set(rows[0]["__headers"]) if rows else None


def _has(headers: set[str], column: str | Sequence[str]) -> bool:
    names = [column] if isinstance(column, str) else list(column)
    for name in names:
        if _key(name) in headers or any(_key(alias) in headers for alias in HEADER_ALIASES.get(_key(name), ())):
            return True
    return False


def _label(column: str | Sequence[str]) -> str:
    return column if isinstance(column, str) else " / ".join(column)


def _missing(headers: set[str] | None, needed: Sequence[str | Sequence[str]]) -> list[str]:
    if headers is None:
        return [_label(c) for c in needed]
    return [_label(c) for c in needed if not _has(headers, c)]


def _sheet(wb, *, equals: Sequence[str] = (), contains: Sequence[str] = ()):
    """The first sheet whose normalised name equals one of ``equals`` or contains all of ``contains``."""
    for name in wb.sheetnames:
        key = _key(name)
        if key in {_key(e) for e in equals} or (contains and all(c in key for c in contains)):
            return wb[name]
    return None


def _report(label: str, missing: list[str]) -> list[str]:
    return [f"{label}: missing column(s) {', '.join(missing)}"] if missing else []


def check_order_file(kind: str, data_path: Path, dispo_path: Path | None = None) -> list[str]:
    """What the Biglietti conversion of ``kind`` (elvy / med / el_kamal) will lack in its input files."""
    try:
        wb = openpyxl.load_workbook(data_path, data_only=True, read_only=True)
    except Exception:  # noqa: BLE001 -- the conversion reports an unreadable file itself
        return []
    try:
        if kind == "el_kamal":
            return _check_kamal(wb)
        return _check_erp_dump(wb, data_path, dispo_path)
    finally:
        wb.close()


def _check_erp_dump(wb, data_path: Path, dispo_path: Path | None) -> list[str]:
    problems: list[str] = []
    order = _sheet(wb, equals=("ordine", "sheet1"))
    if order is None:
        return ["The Order Data file has no “Ordine” or “Sheet1” sheet."]
    problems += _report(f"Sheet “{order.title}”", _missing(_headers(order), ERP_ORDER_COLUMNS))
    external = dispo_path and Path(dispo_path) != Path(data_path)
    if not external:
        dispo = _sheet(wb, contains=("dispo", "bagno"))
        if dispo is None:
            problems.append("No Dispo-Bagno sheet (or file): the tickets will have no Dispo / Bagno.")
        else:
            problems += _report(f"Sheet “{dispo.title}”", _missing(_headers(dispo), DISPO_COLUMNS))
    raw = _sheet(wb, contains=("filato",)) or _sheet(wb, contains=("tinturia",))
    if raw is None:
        problems.append("No Filato x Tinturia sheet: the raw-yarn weight (VMM22) will be empty.")
    return problems


def _check_kamal(wb) -> list[str]:
    ordine = _sheet(wb, equals=("Ordine Kamal",))
    if ordine is None:
        order = _sheet(wb, equals=("sheet1",))
        if order is None:
            return ["The EL KAMAL file has neither an “Ordine Kamal” nor a “Sheet1” sheet."]
        return _report(f"Sheet “{order.title}”", _missing(_headers(order), ("Articolo", "Colore", "Ordine")))
    problems = _report("Sheet “Ordine Kamal”", _missing(_headers(ordine), KAMAL_ORDER_COLUMNS))
    names = _sheet(wb, equals=("Kamal Order",))
    if names is None:
        problems.append("No “Kamal Order” sheet: the colour names will be the short codes.")
    else:
        problems += _report("Sheet “Kamal Order”", _missing(_headers(names), KAMAL_NAME_COLUMNS))
    return problems


def check_med_input(path: Path) -> list[str]:
    """What Ordine MED will lack in its ORDINE workbook (sheet ORDINE, else the first sheet)."""
    try:
        wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
    except Exception:  # noqa: BLE001
        return []
    try:
        sheet = wb["ORDINE"] if "ORDINE" in wb.sheetnames else wb[wb.sheetnames[0]]
        return _report(f"Sheet “{sheet.title}”", _missing(_headers(sheet), MED_ORDER_COLUMNS))
    finally:
        wb.close()
