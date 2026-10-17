"""
abbina_calculator.py — Automatic Abbina assignment for Delta Dyeing order rows.

Business rules (from spec)
--------------------------
1.  Never merge rows with different Colour values.
2.  Only consecutive rows with the same Colour may form one machine group.
3.  Colour comparison is exact (case-sensitive, leading-zeros preserved).
4.  Walk rows top → bottom, grouping while Colour stays identical.
5.  Sum Quantity /Cones for the group.
6.  Assign the *smallest* available machine capacity that is >= the group total.
7.  Write "Machine <capacity> Cones" into every row of that group.

Available machine capacities (ascending order — must stay sorted):
    6, 24, 32, 56, 72, 128, 192, 384, 672

8.  If the group total exceeds the largest machine (672), the group is SPLIT
    into several batches (rows stay in order, a row is never cut): each batch
    is filled up to the largest machine and then gets its own smallest
    fitting machine.  Every batch is numbered in ``OrderRow.abbina_batch`` so
    callers (First Bagno) can tell two same-label batches apart.  Only a
    single row bigger than the largest machine still gets the largest
    machine, with a warning.
"""

from __future__ import annotations

import re

from parsers.pdf_parser import OrderRow
from utility.utils import logger
from calculate.constants import ABBINA_MACHINE_CODES, MACHINE_CAPACITIES


# ---------------------------------------------------------------------------
# Machine capacity table — must remain sorted ascending
# ---------------------------------------------------------------------------

# Backward-compatible alias; the canonical values live in constants.py.
MACHINE_CAPACITIES: list[int] = list(MACHINE_CAPACITIES)

# Physical machine number for each cone capacity — used by the "Ordini
# ELVY" export sheet to turn an Abbina value like "Machine 72 Cones" into
# a MACCHINA code.
MACHINE_CODES: dict[int, int] = dict(ABBINA_MACHINE_CODES)


def _refresh_machine_tables() -> None:
    from calculate import constants as _constants
    MACHINE_CAPACITIES[:] = _constants.MACHINE_CAPACITIES
    MACHINE_CODES.clear()
    MACHINE_CODES.update(_constants.ABBINA_MACHINE_CODES)


from calculate import constants as _constants_module  # noqa: E402
_constants_module.register_machine_listener(_refresh_machine_tables)


def _smallest_fitting_machine(total_cones: float) -> int:
    """Return 0 for an empty group, otherwise the smallest fitting capacity."""
    if total_cones <= 0:
        return 0
    for capacity in MACHINE_CAPACITIES:
        if capacity >= total_cones:
            return capacity
    # total_cones exceeds every machine — use the largest and warn
    logger.warning(
        "    Group total %.2f cones exceeds largest machine (%d). "
        "Assigning largest machine.",
        total_cones, MACHINE_CAPACITIES[-1],
    )
    return MACHINE_CAPACITIES[-1]


def split_into_batches(quantities) -> list[int]:
    """Batch number (0, 1, ...) for every quantity, in order.

    Sequential fill: a row joins the current batch while the batch total stays
    within the largest machine; otherwise it starts the next batch.  Same
    colour/total rules as one machine, just without ever overfilling it.
    """
    limit = MACHINE_CAPACITIES[-1]
    batches: list[int] = []
    batch, total = 0, 0.0
    for q in quantities:
        q = q or 0.0
        if total > 0 and total + q > limit:
            batch += 1
            total = 0.0
        batches.append(batch)
        total += q
    return batches


# ---------------------------------------------------------------------------
# Calculator
# ---------------------------------------------------------------------------

class AbbinaCalculator:
    """
    Assign Abbina values to a list of :class:`~pdf_parser.OrderRow` objects
    **in-place** using the automatic grouping rules.

    Usage::

        rows = PDFParser(path).parse()
        AbbinaCalculator().calculate(rows)
        # rows[i].abbina is now set for every row
    """

    def calculate(self, rows: list[OrderRow], only_if_missing: bool = False) -> None:
        """
        Walk *rows* and set ``abbina`` on each row.

        Groups are formed by consecutive rows that share the same ``colour``
        value (exact string match).  Each group is assigned the smallest
        machine that can hold its total ``quantity_cones``.

        only_if_missing
        ----------------
        When True, a group is only touched if NONE of its rows already have
        an ``abbina`` value (e.g. extracted from a PDF annotation) — groups
        that already have one are left exactly as they are. This powers the
        mandatory hybrid behaviour: PDF-provided Abbina wins where present,
        automatic calculation fills in the gaps.
        """
        if not rows:
            return

        i = 0
        while i < len(rows):
            colour = rows[i].colour
            group_start = i
            total_cones: float = 0.0

            # Extend the group while colour stays identical
            while i < len(rows) and rows[i].colour == colour:
                total_cones += rows[i].quantity_cones or 0.0
                i += 1

            group_end = i  # exclusive slice index

            if only_if_missing and any(rows[j].abbina for j in range(group_start, group_end)):
                given = next(rows[j].abbina for j in range(group_start, group_end) if rows[j].abbina)
                m = re.search(r"(\d+)", given)
                if m and total_cones > int(m.group(1)):
                    logger.warning(
                        "    Colour %r: PDF Abbina '%s' is smaller than the group total (%.0f cones) -- kept as given.",
                        colour, given, total_cones,
                    )
                # Some rows of the run carry an Abbina and some do not (a machine
                # line in the middle of one colour): the blank rows belong to the
                # same machine, so they take the nearest label instead of being
                # left without a machine.
                last = ""
                for j in range(group_start, group_end):
                    if rows[j].abbina:
                        last = rows[j].abbina
                    elif last:
                        rows[j].abbina = last
                for j in range(group_start, group_end):
                    if not rows[j].abbina:
                        rows[j].abbina = given
                continue

            run = rows[group_start:group_end]
            batch_ids = split_into_batches([r.quantity_cones for r in run])
            for batch in sorted(set(batch_ids)):
                members = [r for r, b in zip(run, batch_ids) if b == batch]
                batch_total = sum(r.quantity_cones or 0.0 for r in members)
                label = f"Machine {_smallest_fitting_machine(batch_total)} Cones"
                for r in members:
                    r.abbina = label
                    r.abbina_batch = batch
            label = f"{len(set(batch_ids))} batch(es)"

            logger.debug(
                "    Abbina group colour=%r rows %d–%d  "
                "total=%.2f → %s",
                colour, group_start + 1, group_end,
                total_cones, label,
            )
