"""CONSEGNA (delivery date) -- one rule for ELVY, MED and EL KAMAL.

A colour queued on a machine is finished when the machine's coverage runs out (two colours a
day per machine, Fridays excluded -- ``calculate.situazione.machine_coverage_until``) and is
delivered ``CONSEGNA_LEAD_DAYS`` (14) days after that.  A row without a machine, or whose
machine has no coverage date, is delivered 14 days from today.  An order that already asks
for a later date keeps it (Ordine MED only: ELVY and Kamal orders carry no requested date).

``machine_totals`` is ``{machine number: colours already queued}`` -- the same baseline the
Overview / Copertura window shows (``situazione_logic.compute_machine_totals``).  Every row of
the order counts as one more colour on its machine, so the dates of one order step forward
together exactly as they do for Ordine MED.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Iterable, Mapping

from calculate import situazione   # attributes are read at call time, exactly as Ordine MED always did

CONSEGNA_LEAD_DAYS = 14


class ConsegnaPlanner:
    """Hands out the delivery date of each row of one order, in order."""

    def __init__(self, machine_totals: Mapping[int, int] | None = None, today: date | None = None) -> None:
        self._totals = dict(machine_totals or {})
        self._fixed_today = today          # None = the real today (what the coverage helper uses by default)
        self._today = today or datetime.now().date()
        self._running: dict[int, int] = {}

    def base_date(self, machine_label) -> date:
        """The delivery date of the next row on *machine_label* (a 3300-series code, a bare
        machine number, or empty).  Every call counts one more colour on that machine."""
        delivery = self._today + timedelta(days=CONSEGNA_LEAD_DAYS)
        machine = situazione.machine_number_from_label(str(machine_label)) if machine_label else None
        if machine is not None:
            self._running[machine] = self._running.get(machine, 0) + 1
            queued = self._totals.get(machine, 0) + self._running[machine]
            covered = (situazione.machine_coverage_until(queued) if self._fixed_today is None
                       else situazione.machine_coverage_until(queued, self._fixed_today))
            if covered != "-":
                delivery = datetime.strptime(covered, "%Y-%m-%d").date() + timedelta(days=CONSEGNA_LEAD_DAYS)
        return delivery


def apply_order_consegna(rows: Iterable, machine_totals: Mapping[int, int] | None,
                         machine_attr: str = "macchina", today: date | None = None) -> None:
    """Set ``data_consegna`` (and ``data_riconsegna`` = the day before) on ELVY / Kamal order
    rows, in place.  The machine of every row must already be assigned."""
    planner = ConsegnaPlanner(machine_totals, today)
    for row in rows:
        consegna = datetime.combine(planner.base_date(getattr(row, machine_attr, None)), time.min)
        row.data_consegna = consegna
        row.data_riconsegna = consegna - timedelta(days=1)
