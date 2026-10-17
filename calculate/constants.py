"""Shared business constants used by the planning and export modules."""
from __future__ import annotations

import logging
from typing import Callable

_log = logging.getLogger(__name__)

_DEFAULT_MACHINE_ROWS = (
    ("3300", "4", "672"), ("3301", "11", "6"), ("3310", "12", "24"), ("3306", "9", "32"),
    ("3302", "10", "56"), ("3307", "7", "72"), ("3303", "8", "128"),
    ("3308", "5", "192"), ("3304", "6", "384"), ("3309", "3", "672"),
)


def valid_machine_rows(raw_rows) -> tuple[tuple[str, str, int], ...]:
    """(code, number, capacity) for every usable machine row.

    A row is usable when code, number and capacity are all positive whole
    numbers and its code and number are not already taken by an earlier row.
    Anything else is skipped (and logged) -- a bad value saved in Master Data
    must never stop the application from starting.
    """
    rows: list[tuple[str, str, int]] = []
    codes: set[int] = set()
    numbers: set[int] = set()
    for raw in raw_rows or ():
        try:
            code = int(str(raw["code"]).strip())
            number = int(str(raw["number"]).strip())
            capacity = int(str(raw["rocche"]).strip())
        except (KeyError, TypeError, ValueError):
            _log.warning("Ignoring machine row with a non-numeric value: %r", raw)
            continue
        if code <= 0 or number <= 0 or capacity <= 0 or code in codes or number in numbers:
            _log.warning("Ignoring invalid or duplicate machine row: %r", raw)
            continue
        codes.add(code)
        numbers.add(number)
        rows.append((str(code), str(number), capacity))
    return tuple(rows)


def _load_machine_rows() -> tuple[tuple[str, str, int], ...]:
    rows: tuple[tuple[str, str, int], ...] = ()
    try:
        from utility.master_data import load as _load_master_data
        rows = valid_machine_rows(_load_master_data().get("machines", []))
    except (KeyError, TypeError, ValueError, OSError):
        rows = ()
    if not rows:
        rows = valid_machine_rows(
            {"code": c, "number": n, "rocche": r} for c, n, r in _DEFAULT_MACHINE_ROWS
        )
    if not any(int(number) == 4 for _code, number, _capacity in rows):
        rows += (("3300", "4", 672),)
    return rows


# These objects are updated IN PLACE by reload_machines(), so every module that
# imported them sees a new capacity straight away (no restart needed).
MACHINE_CAPACITIES: list[int] = []          # ordered from the smallest to the largest machine
ABBINA_MACHINE_CODES: dict[int, int] = {}   # machine identifiers depend on the output domain,
SUGGESTION_MACHINE_NUMBERS: dict[int, int] = {}   # so they remain separate
MACHINE_NUMBER_BY_CODE: dict[int, int] = {}
MACHINE_CAPACITY_BY_NUMBER: dict[int, int] = {}

_listeners: list[Callable[[], None]] = []


def register_machine_listener(callback: Callable[[], None]) -> None:
    """Call *callback* after every reload -- for modules that derive their own
    tables from the constants above (they cannot be updated in place)."""
    _listeners.append(callback)


def reload_machines() -> None:
    """Re-read Master Data's machine table and update every constant in place."""
    rows = _load_machine_rows()
    MACHINE_CAPACITIES[:] = sorted(row[2] for row in rows)
    for table, build in (
        (ABBINA_MACHINE_CODES, {capacity: int(code) for code, _n, capacity in rows}),
        (SUGGESTION_MACHINE_NUMBERS, {capacity: int(number) for _c, number, capacity in rows}),
        (MACHINE_NUMBER_BY_CODE, {int(code): int(number) for code, number, _cap in rows}),
        (MACHINE_CAPACITY_BY_NUMBER, {int(number): int(capacity) for _c, number, capacity in rows}),
    ):
        table.clear()
        table.update(build)
    for callback in list(_listeners):
        try:
            callback()
        except Exception:  # noqa: BLE001 -- one stale consumer must not block the others
            _log.exception("Machine table listener failed")


reload_machines()
