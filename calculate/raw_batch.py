"""What a "Partita GG" (raw yarn batch) value means for an order row.

Three kinds of value can sit in that place:

* blank / "X" / "PG-X"  -- no raw yarn assigned yet (the row waits in PG-X);
* a number starting with 1 (e.g. 159233) -- one of OUR raw batches: assigned;
* for the MED customer only, any other number (e.g. 837756) -- the customer's own
  lot.  It is not our raw batch: the row still waits in PG-X, Smart Auto-Assign
  uses the number to find the stock, and "Print Assigned PG-X" must not print it.

Every screen asks these helpers instead of repeating the rule.
"""
from __future__ import annotations

from typing import Any

MED_CODE = "3004"                                   # ERP customer code of MED
_NO_BATCH = {"", "X", "PG-X", "PGX"}


def normalize(value: Any) -> str:
    """The batch as comparable text: trimmed, upper-case, without spaces."""
    return str(value or "").strip().upper().replace(" ", "")


def is_blank_raw(value: Any) -> bool:
    """True when no raw batch (not even a customer lot) is recorded."""
    return normalize(value) in _NO_BATCH


def is_customer_lot(raw_batch: Any, customer_code: Any = "") -> bool:
    """True for a MED customer lot: a number that does not start with 1."""
    text = normalize(raw_batch)
    return str(customer_code) == MED_CODE and text not in _NO_BATCH and not text.startswith("1")


def is_assigned_raw(raw_batch: Any, customer_code: Any = "") -> bool:
    """True when the row carries one of our own raw batches."""
    return not is_blank_raw(raw_batch) and not is_customer_lot(raw_batch, customer_code)
