"""bagno.py -- "First Bagno" sequencing shared by Ordine Elvy and Ordine Kamal.

Same principle as Ordine MED (``pipelines.ordine_med.assign_bagno_prepostato``),
but MED decides "which rows dye together" from the ABBIN column, whereas Elvy
and Kamal have no ABBIN: rows dye together when they end up on the same
machine batch (same colour group -- see ``abbina_calculator`` for Elvy and
``ordine_kamal._machine_group_key`` for Kamal).

How the numbers work
--------------------
* The operator types the bath number the ERP will give to the *next* bath it
  creates (``First bagno``, e.g. ``T1200``).
* Every bath (= every group of rows sharing one machine batch) takes one
  step of the counter, in the order the groups first appear in the order.
* The first row of a group is the real start of the bath, so its BAGNO
  PREPOSTO stays blank (the ERP numbers it by itself).  Every following row
  of the same group is "pre-posted" onto that bath, so it carries the number.
* A row that belongs to no group (no machine batch could be worked out) is a
  bath of its own: it takes a counter step and stays blank.
"""

from __future__ import annotations

import re
from typing import Any, Hashable, Sequence

_FIRST_BAGNO_RE = re.compile(r"\s*([A-Za-z]+)\s*(\d+)\s*")

FIRST_BAGNO_FORMAT_ERROR = "Il primo bagno deve avere il formato, ad esempio, T1200."


def parse_first_bagno(text: Any) -> tuple[str, int]:
    """'T1200' -> ('T', 1200).  Raises ValueError for anything else."""
    match = _FIRST_BAGNO_RE.fullmatch(str(text or ""))
    if not match:
        raise ValueError(FIRST_BAGNO_FORMAT_ERROR)
    prefix, number = match.groups()
    return prefix, int(number)


def is_valid_first_bagno(text: Any) -> bool:
    try:
        parse_first_bagno(text)
    except ValueError:
        return False
    return True


def sequence_bagno(group_keys: Sequence[Hashable | None], first_bagno: str | None) -> list[str]:
    """Return the BAGNO PREPOSTO value for every row, in row order.

    ``group_keys[i]`` identifies the machine batch row *i* belongs to (rows
    with equal keys are dyed together, wherever they sit in the order).
    ``None`` means "no group": the row is a bath on its own.

    An empty / missing ``first_bagno`` disables the feature (all blank).
    A malformed one raises ValueError, even for an empty row list, so a bad
    entry is reported instead of silently ignored.
    """
    result = [""] * len(group_keys)
    if not first_bagno or not str(first_bagno).strip():
        return result
    prefix, next_number = parse_first_bagno(first_bagno)

    bagno_of_group: dict[Hashable, str] = {}
    for index, key in enumerate(group_keys):
        if key is None:
            next_number += 1  # a lone row still occupies one bath position
            continue
        if key not in bagno_of_group:
            bagno_of_group[key] = f"{prefix}{next_number}"
            next_number += 1
            continue  # first row of the group: real bath start -> blank
        result[index] = bagno_of_group[key]
    return result
