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


# --------------------------------------------------------------------------- fast per-cell styling
# ``cell.font = ...`` / ``cell.alignment = ...`` make openpyxl hash and compare the style object for EVERY cell
# (about 80 microseconds each; a 600-row export spent ~5 s on it) although a sheet only ever uses a handful of
# distinct styles.  ``register_style`` registers a combination once in the workbook and ``apply_style`` writes the
# resulting indices straight into a cell's style array -- exactly what the descriptors do, without the repeated hashing.
def register_style(workbook, font=None, border=None, fill=None, alignment=None, number_format=None) -> tuple:
    """Register the given style parts in *workbook* once; the result is passed to ``apply_style`` for every cell."""
    from openpyxl.styles.numbers import BUILTIN_FORMATS_MAX_SIZE, BUILTIN_FORMATS_REVERSE

    ids = []
    if font is not None:
        ids.append(("fontId", workbook._fonts.add(font)))
    if border is not None:
        ids.append(("borderId", workbook._borders.add(border)))
    if fill is not None:
        ids.append(("fillId", workbook._fills.add(fill)))
    if alignment is not None:
        ids.append(("alignmentId", workbook._alignments.add(alignment)))
    if number_format is not None:
        if number_format in BUILTIN_FORMATS_REVERSE:
            ids.append(("numFmtId", BUILTIN_FORMATS_REVERSE[number_format]))
        else:
            ids.append(("numFmtId", workbook._number_formats.add(number_format) + BUILTIN_FORMATS_MAX_SIZE))
    return tuple(ids)


def apply_style(cell, registered: tuple) -> None:
    """Give *cell* the style parts of a ``register_style`` result; the parts it does not name are left as they are."""
    from openpyxl.styles.cell_style import StyleArray

    style = cell._style
    if not style:                      # a cell nobody styled yet has no style array (the descriptors do the same)
        style = cell._style = StyleArray()
    for key, index in registered:
        setattr(style, key, index)
