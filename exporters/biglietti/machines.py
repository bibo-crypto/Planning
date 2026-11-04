"""جدول أحجام الماكينات واختيار الماكينة حسب عدد الرُوقات.

جزء من حزمة exporters.biglietti (انظر ARCHITECTURE_AR.md). الواجهة القديمة
exporters/biglietti_exporter.py تعيد تصدير كل الأسماء من هنا."""

from __future__ import annotations

from calculate.constants import MACHINE_CAPACITIES

MACHINE_SIZE_TABLE: dict[int, int] = {
    capacity: machine for capacity, machine in zip(
        MACHINE_CAPACITIES, (11, 12, 9, 10, 7, 8, 5, 6, 3)
    )
}


def _refresh_machine_size_table() -> None:
    """Master Data is the source of truth: capacity -> machine number.  (For the
    default machines this is exactly the table above.)"""
    from calculate import constants as _constants
    MACHINE_SIZE_TABLE.clear()
    MACHINE_SIZE_TABLE.update(_constants.SUGGESTION_MACHINE_NUMBERS)


from calculate import constants as _constants_module  # noqa: E402

_constants_module.register_machine_listener(_refresh_machine_size_table)


MACHINE_SIZE_TABLE_MED_EXTRA: dict[int, int] = {7: 11}

# A nearest-size match is only accepted within this tolerance (fraction of
# the nearest table size); anything further is left blank for a human to
# check, per "لو غير مطابقه بيقربها لأقرب ماكينه ولو بعيد سيبه فاضي".
_MACHINE_MATCH_TOLERANCE = 0.15


def _machine_for_count(count: float | int | None, extra: dict[int, int] | None = None) -> str:
    """Return a machine number; non-positive or missing count means blank."""
    if count is None or count <= 0:
        return ""
    table = dict(MACHINE_SIZE_TABLE)
    if extra:
        table.update(extra)
    if count in table:
        return str(table[count])
    nearest = min(table, key=lambda k: abs(k - count))
    if abs(nearest - count) <= nearest * _MACHINE_MATCH_TOLERANCE:
        return str(table[nearest])
    return ""
