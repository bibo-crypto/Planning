"""Value hygiene for the workbooks the program writes for Excel and the ERP.

Excel answers "We found a problem with some content ... do you want us to try to recover as much
as we can?" when a worksheet holds

* a text cell with no text -- openpyxl writes ``""`` as ``<c t="inlineStr"></c>``;
* a numeric cell with no number -- ``NaN`` / ``inf`` (pandas produces NaN for every blank cell)
  become ``<c><v></v></c>``.

(openpyxl already cuts text at Excel's 32,767-character limit.)

``sanitize_workbook`` removes both just before a workbook is saved (``safe_save_workbook``
calls it), and ``describe_invalid_cells`` re-checks the saved file so a broken workbook can never
replace a good one.  ``to_excel_date`` turns every shape a date arrives in (text with or without
a time, ``date``, numpy/pandas values, Excel serial numbers) into a real date.
"""
from __future__ import annotations

import math
import re
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

# --------------------------------------------------------------------------------------- dates
_DATE_ONLY = (
    "%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y", "%d.%m.%Y", "%Y/%m/%d",
    "%d %b %Y", "%d %B %Y", "%b %d, %Y", "%B %d, %Y", "%d-%b-%Y", "%d-%b-%y",
)
_WITH_TIME = (
    "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%S.%f",
    "%d/%m/%Y %H:%M:%S", "%d/%m/%Y %H:%M", "%d-%m-%Y %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M",
    "%Y/%m/%d %H:%M:%S",
)
_SERIAL_TEXT = re.compile(r"^\d{5}(?:\.0+)?$")
_EXCEL_EPOCH = datetime(1899, 12, 30)


def _midnight(value: datetime) -> datetime:
    return value.replace(hour=0, minute=0, second=0, microsecond=0)


def _from_serial(number: float) -> datetime | None:
    return _EXCEL_EPOCH + timedelta(days=float(number)) if 20000 < float(number) < 80000 else None


def to_excel_date(value):
    """A real date (a midnight ``datetime``) whenever *value* can be read as one.

    * blank, ``NaN`` and ``NaT`` (an empty cell read by pandas) -> ``None``;
    * ``datetime`` / ``date`` / ``numpy.datetime64`` / pandas ``Timestamp`` -> the day;
    * text such as ``20/10/2026``, ``2026-10-20 00:00:00``, ``20/10/2026 10:30``,
      ``20 Oct 2026`` or an Excel serial number written as text -> the day;
    * a number in the Excel serial range -> the day;
    * anything else is returned **unchanged**, so no information is ever lost.
    """
    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, datetime):
        return None if value != value else _midnight(value)          # NaT != NaT
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if type(value).__name__ == "datetime64":                          # numpy, imported only when needed
        import numpy as np
        if np.isnat(value):
            return None
        return _midnight(datetime.fromisoformat(str(np.datetime_as_string(value, unit="s"))))
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return _from_serial(value) or value
    if not isinstance(value, str):
        return value
    text = value.strip()
    if not text or text.lower() in ("nan", "nat", "none"):       # a blank that was turned into text
        return None
    if _SERIAL_TEXT.match(text):
        return _from_serial(float(text)) or value
    for fmt in _DATE_ONLY:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    for fmt in _WITH_TIME:
        try:
            return _midnight(datetime.strptime(text, fmt))
        except ValueError:
            continue
    return value


# ----------------------------------------------------------------------------------- hygiene
def sanitize_workbook(workbook) -> int:
    """Make every cell of *workbook* something Excel accepts; returns how many were changed.

    ``""`` -> an empty cell, ``NaN`` / ``inf`` / ``NaT`` -> an empty cell.  Formulas are left alone."""
    changed = 0
    for sheet in getattr(workbook, "worksheets", []):
        cells = getattr(sheet, "_cells", None)          # absent in write-only workbooks
        if not cells:
            continue
        for cell in list(cells.values()):
            value = cell._value
            if value is None:
                continue
            if isinstance(value, str):
                if value == "":
                    cell.value = None
                    changed += 1
            elif isinstance(value, float):
                if math.isnan(value) or math.isinf(value):
                    cell.value = None
                    changed += 1
            elif isinstance(value, datetime) and value != value:      # pandas NaT
                cell.value = None
                changed += 1
    return changed


_EMPTY_TEXT_CELL = re.compile(rb'<c\b[^>]*\bt="inlineStr"[^>]*(?:/>|>\s*</c>)')
_CELL_VALUE = re.compile(rb"<c\b([^>]*)>\s*<v>([^<]*)</v>")
_NOT_NUMERIC_TYPES = (b't="s"', b't="str"', b't="inlineStr"', b't="b"', b't="e"')


def describe_invalid_cells(path: Path) -> str | None:
    """None when every worksheet of the saved workbook is clean, else a short description of the
    first cell Excel would refuse."""
    try:
        archive = zipfile.ZipFile(path)
    except (zipfile.BadZipFile, OSError):
        return None                                      # not our job: the validity check reports it
    with archive:
        for name in archive.namelist():
            if not re.match(r"xl/worksheets/sheet\d+\.xml$", name):
                continue
            data = archive.read(name)
            if _EMPTY_TEXT_CELL.search(data):
                return f"{name}: a text cell with no text"
            for attributes, number in _CELL_VALUE.findall(data):
                if any(kind in attributes for kind in _NOT_NUMERIC_TYPES):
                    continue
                try:
                    float(number)
                except ValueError:
                    return f"{name}: a numeric cell holding {number.decode('utf-8', 'replace')!r}"
                if number.strip().lower() in (b"nan", b"inf", b"-inf"):
                    return f"{name}: a numeric cell holding {number.decode()!r}"
    return None
