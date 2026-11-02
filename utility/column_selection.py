"""Which columns of each output sheet the planner wants.

Single responsibility: remember, per page and per sheet, the columns the user turned
OFF, and filter a column list / header list / value row accordingly.  No Tk and no
Excel in here -- the pages open the picker (gui/column_picker.py), the exporters call
the small filter helpers below.

Why "hidden" and not "selected": a column that is added to the program later has never
been seen by the user, so it must show up by default.  Storing only what was switched
off gives exactly that, and an empty file means "everything, as before".

Storage: ``settings/column_selection.json``::

    {"ordine_med": {"hidden": {"Ordine da creare": ["NOTA grg"]},
                    "order": {"Ordine da creare": ["CLIENTE", "ARTICOLO", ...]}}}

The same file keeps the ORDER the planner dragged the columns into (``"order"`` below);
a column the saved order does not know (added to the program later) goes after the others.

A sheet can never end up with no column at all: if every column of a sheet is switched
off, the filters below return the full list instead (an empty sheet is never useful).
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Collection, Iterable, Mapping, Sequence, TypeVar

from utility.atomic import atomic_write_text
from utility.utils import APP_DATA_DIR, logger

T = TypeVar("T")

COLUMN_SELECTION_FILE: Path = APP_DATA_DIR / "settings" / "column_selection.json"

# Biglietti page -> the customer code printed on its tickets (see exporters.biglietti_exporter).
BIGLIETTI_CUSTOMER_CODES: dict[str, str] = {
    "biglietti_elvy": "3009",
    "biglietti_med": "3004",
    "biglietti_el_kamal": "3019",
}
# Biglietti page -> the name of its Excel sheet (the customer's own sheet).
BIGLIETTI_SHEET_NAMES: dict[str, str] = {
    "biglietti_elvy": "ELVY",
    "biglietti_med": "MED",
    "biglietti_el_kamal": "EL_KAMAL",
}

_lock = threading.RLock()


# --------------------------------------------------------------------------- storage
class SheetChoice(frozenset):
    """The labels switched off for one sheet (a frozenset), plus the column order the planner chose.

    Because it is a frozenset every consumer that only asks "is this label hidden?" keeps
    working; visible_positions() also honours ``order``.
    """
    order: tuple[str, ...] = ()

    def __new__(cls, hidden: Iterable[str] = (), order: Iterable[str] = ()):
        obj = super().__new__(cls, hidden)
        obj.order = tuple(order)
        return obj


def _read_all() -> dict[str, dict[str, dict[str, list[str]]]]:
    """The whole file as {page: {"hidden": {sheet: [...]}, "order": {sheet: [...]}}}; a missing or broken file is "nothing chosen"."""
    try:
        if not COLUMN_SELECTION_FILE.is_file():
            return {}
        data = json.loads(COLUMN_SELECTION_FILE.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001 -- a damaged settings file must never stop an export
        logger.warning("Could not read the column selection: %s", exc)
        return {}
    if not isinstance(data, dict):
        return {}
    clean: dict[str, dict[str, dict[str, list[str]]]] = {}
    for page, kinds in data.items():
        if not isinstance(kinds, dict):
            continue
        clean[str(page)] = {
            kind: {
                str(sheet): [str(label) for label in labels]
                for sheet, labels in (kinds.get(kind) or {}).items()
                if isinstance(labels, list)
            }
            for kind in ("hidden", "order")
            if isinstance(kinds.get(kind) or {}, dict)
        }
    return clean


def load_hidden(page_key: str) -> dict[str, SheetChoice]:
    """{sheet title: SheetChoice} for one page: what is switched off and the chosen order.

    Only sheets the user changed are listed (an empty dict means "everything, as before")."""
    with _lock:
        kinds = _read_all().get(page_key, {})
    hidden, order = kinds.get("hidden", {}), kinds.get("order", {})
    return {
        sheet: SheetChoice(hidden.get(sheet, ()), order.get(sheet, ()))
        for sheet in set(hidden) | set(order)
        if hidden.get(sheet) or order.get(sheet)
    }


def load_order(page_key: str) -> dict[str, tuple[str, ...]]:
    """{sheet title: labels in the chosen order} (what the picker shows first)."""
    return {sheet: choice.order for sheet, choice in load_hidden(page_key).items() if choice.order}


def save_hidden(
    page_key: str,
    hidden: Mapping[str, Iterable[str]],
    order: Mapping[str, Iterable[str]] | None = None,
) -> None:
    """Replace the saved choice of one page.  Sheets with nothing changed are not stored."""
    with _lock:
        data = _read_all()
        kept_hidden = {sheet: sorted(set(labels)) for sheet, labels in hidden.items() if set(labels)}
        kept_order = {sheet: list(labels) for sheet, labels in (order or {}).items() if list(labels)}
        if kept_hidden or kept_order:
            data[page_key] = {"hidden": kept_hidden, "order": kept_order}
        else:
            data.pop(page_key, None)
        try:
            atomic_write_text(COLUMN_SELECTION_FILE, json.dumps(data, indent=2, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001 -- the choice just is not remembered
            logger.warning("Could not save the column selection: %s", exc)


def reset(page_key: str) -> None:
    """Forget the choice of one page: every column is shown again."""
    save_hidden(page_key, {})


def hidden_for_sheet(page_key: str, sheet: str) -> frozenset[str]:
    """The labels switched off for one sheet of one page."""
    return load_hidden(page_key).get(sheet, frozenset())


def ticket_hidden_by_customer_code() -> dict[str, frozenset[str]]:
    """{customer code: labels switched off} for the Word tickets.

    A ticket prints what the customer's Excel sheet shows, so the Biglietti page's choice
    for that sheet is the choice for the ticket as well.
    """
    return {
        code: frozenset(hidden_for_sheet(page, BIGLIETTI_SHEET_NAMES[page]))
        for page, code in BIGLIETTI_CUSTOMER_CODES.items()
    }


# --------------------------------------------------------------------------- filtering
def visible_positions(headers: Sequence[Any], hidden: Collection[str] | None) -> list[int]:
    """Indexes of the headers that stay, in the chosen order (the file order when none was chosen).

    Nothing hidden -- or everything hidden -- keeps them all.  ``hidden`` may be a SheetChoice
    carrying the dragged order; labels the order does not know follow the others.
    """
    names = [str(header) for header in headers]
    order = getattr(hidden, "order", ()) or ()
    hidden = hidden or ()
    positions = [i for i, name in enumerate(names) if name not in hidden]
    if not positions:
        positions = list(range(len(names)))
    if order:
        rank = {label: n for n, label in enumerate(order)}
        positions.sort(key=lambda i: (rank.get(names[i], len(rank)), i))
    return positions


def pick_headers(headers: Sequence[T], hidden: Collection[str] | None) -> list[T]:
    """The headers that stay, in their original order."""
    return [headers[i] for i in visible_positions(headers, hidden)]


def pick_values(values: Sequence[T], positions: Sequence[int]) -> list[T]:
    """One data row reduced to the columns at ``positions`` (from visible_positions)."""
    return [values[i] for i in positions]


def pick_columns(columns: Sequence[tuple[str, str, str]], hidden: Collection[str] | None) -> list[tuple[str, str, str]]:
    """The (label, attribute, type) column definitions of excel_exporter that stay."""
    positions = visible_positions([label for label, _attr, _kind in columns], hidden)
    return [columns[i] for i in positions]
