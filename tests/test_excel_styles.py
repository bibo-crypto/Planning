"""The three table exporters share one set of styling constants (exporters/excel_styles.py).

These tests pin today's look so that changing it is a conscious edit, and prove the
exporters really use the shared objects (the old copy-paste could drift apart silently).
"""
import pytest

from exporters import bolla_exporter, elvy_invoice_exporter, excel_exporter, excel_styles

NAMES = ("HEADER_FILL", "HEADER_FONT", "BODY_FONT", "CELL_BORDER", "NUMBER_FORMAT")


@pytest.mark.parametrize("module", [excel_exporter, bolla_exporter, elvy_invoice_exporter])
@pytest.mark.parametrize("name", NAMES)
def test_every_exporter_uses_the_shared_object(module, name):
    assert getattr(module, name) is getattr(excel_styles, name)


def test_the_shared_values_are_the_ones_the_exporters_always_had():
    fill = excel_styles.HEADER_FILL
    assert (fill.fill_type, fill.fgColor.rgb) == ("solid", "00BDD7EE")
    header, body = excel_styles.HEADER_FONT, excel_styles.BODY_FONT
    assert (header.b, header.name, header.sz) == (True, "Calibri", 11)
    assert (bool(body.b), body.name, body.sz) == (False, "Calibri", 11)
    border = excel_styles.CELL_BORDER
    for side in (border.left, border.right, border.top, border.bottom):
        assert (side.style, side.color.rgb) == ("thin", "00D9D9D9")
    assert excel_styles.THIN_BORDER_SIDE.style == "thin"
    assert excel_styles.NUMBER_FORMAT == "#,##0.00"
