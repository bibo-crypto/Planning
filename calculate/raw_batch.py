"""What a "Partita GG" (raw yarn batch) value means for an order row.

Three kinds of value can sit in that place:

* blank / "X" / "PG-X"  -- no raw yarn assigned yet (the row waits in PG-X);
* a number starting with 1 (e.g. 159233) -- one of OUR raw batches: assigned;
* for MED and ELVY, anything else -- the customer's own lot: a number that does not
  start with 1 for MED (e.g. 837756), numbers and/or letters for ELVY (e.g. 52_LOT
  1251B.3).  It is not our raw batch: the row still waits in PG-X, Smart Auto-Assign
  uses it to find the stock, and "Print Assigned PG-X" must not print it.

Every screen asks these helpers instead of repeating the rule.
"""
from __future__ import annotations

from typing import Any

MED_CODE = "3004"                                   # ERP customer code of MED
ELVY_CODE = "3009"                                  # ... and of ELVY
LOT_CUSTOMER_CODES = {MED_CODE, ELVY_CODE}          # customers whose own lot can sit in Partita GG
_NO_BATCH = {"", "X", "PG-X", "PGX"}


def normalize(value: Any) -> str:
    """The batch as comparable text: trimmed, upper-case, without spaces."""
    return str(value or "").strip().upper().replace(" ", "")


def is_blank_raw(value: Any) -> bool:
    """True when no raw batch (not even a customer lot) is recorded."""
    return normalize(value) in _NO_BATCH


def is_our_batch(value: Any) -> bool:
    """True for one of OUR raw batches: digits only, starting with 1 (e.g. 159233)."""
    text = normalize(value)
    return text.isdigit() and text.startswith("1")


def is_customer_lot(raw_batch: Any, customer_code: Any = "") -> bool:
    """True for a MED / ELVY customer lot: a recorded value that is not one of our batches."""
    return (
        str(customer_code) in LOT_CUSTOMER_CODES
        and not is_blank_raw(raw_batch)
        and not is_our_batch(raw_batch)
    )


def is_assigned_raw(raw_batch: Any, customer_code: Any = "") -> bool:
    """True when the row carries one of our own raw batches."""
    return not is_blank_raw(raw_batch) and not is_customer_lot(raw_batch, customer_code)
