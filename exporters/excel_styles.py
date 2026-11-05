"""Styling constants shared by the table-style Excel exporters.

``excel_exporter.py``, ``bolla_exporter.py`` and ``elvy_invoice_exporter.py`` used to
define these by copy-paste (one of them even carried a "matches excel_exporter.py"
comment).  They now import the same objects from here, under the same names, so
``excel_exporter.HEADER_FILL`` and friends keep working for any caller.

Changing a value here changes the look of all three workbooks at once -- that is the
point; ``tests/test_excel_styles.py`` pins today's values so it is a conscious edit.
"""
from openpyxl.styles import Border, Font, PatternFill, Side

HEADER_FILL = PatternFill("solid", fgColor="BDD7EE")   # light blue
HEADER_FONT = Font(bold=True, name="Calibri", size=11)
BODY_FONT = Font(name="Calibri", size=11)
THIN_BORDER_SIDE = Side(style="thin", color="D9D9D9")
CELL_BORDER = Border(
    left=THIN_BORDER_SIDE, right=THIN_BORDER_SIDE,
    bottom=THIN_BORDER_SIDE, top=THIN_BORDER_SIDE,
)

NUMBER_FORMAT = "#,##0.00"
