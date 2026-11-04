"""Characterization tests for the Bolla grouping rule, number parser and Excel export
(parsers/bolla_parser.py and exporters/bolla_exporter.py were not covered at all)."""
import openpyxl

from exporters.bolla_exporter import BollaExporter
from parsers.bolla_parser import BollaRow, BollaTotals, group_rows_by_lot, parse_euro_number


def _row(**kw):
    base = dict(bolla_no="B1", bolla_date="01/01/2026", articolo="G130001S", descrizione="COTONE",
                colore="007777", partita="140849", rocche=10.0, kg_netto=25.5)
    base.update(kw)
    return BollaRow(**base)


def test_parse_euro_number():
    assert parse_euro_number("260,30") == 260.3
    assert parse_euro_number("1.111,30") == 1111.3
    assert parse_euro_number("") is None
    assert parse_euro_number("abc") is None


def test_group_rows_by_lot_sums_matching_rows_keeps_first_seen_order_and_treats_none_as_zero():
    rows = [
        _row(partita="P2", rocche=1.0, kg_netto=2.0),
        _row(partita="P1", rocche=10.0, kg_netto=25.0),
        _row(bolla_no="B2", partita="P1", rocche=None, kg_netto=0.5),   # same lot from another Bolla: summed
        _row(partita="P1", colore="000001", rocche=3.0, kg_netto=4.0),  # other colour: separate row
    ]
    grouped = group_rows_by_lot(rows)
    assert [(g.partita, g.colore, g.rocche, g.kg_netto) for g in grouped] == [
        ("P2", "007777", 1.0, 2.0),
        ("P1", "007777", 10.0, 25.5),
        ("P1", "000001", 3.0, 4.0),
    ]


def test_exporter_writes_a_summary_and_a_totals_sheet(tmp_path):
    rows = [_row(rocche=10.0, kg_netto=25.5), _row(bolla_no="B2", rocche=5.0, kg_netto=1.25)]
    totals = [BollaTotals(bolla_no="B1", bolla_date="01/01/2026", n_colli=3, n_pallet=1, tara_tub=0.5,
                          tara_scat=0.25, rocche=10, netto=25.5, lordo=27.0)]
    out = tmp_path / "out" / "bolle.xlsx"
    BollaExporter(rows, totals, out).export()

    wb = openpyxl.load_workbook(out)
    assert wb.sheetnames == ["Summary", "Totals"]
    summary = wb["Summary"]
    assert [c.value for c in summary[1]] == ["Articolo", "Descrizione", "Colore", "Partita", "Rocche", "KgNetto"]
    # the two rows share the lot, so one summed row; Colore/Partita are real numbers (leading zeros drop)
    assert [c.value for c in summary[2]] == ["G130001S", "COTONE", 7777, 140849, 15, 26.75]
    assert summary.max_row == 2
    assert summary.freeze_panes == "A2"
    assert summary.auto_filter.ref == "A1:F2"
    totals_sheet = wb["Totals"]
    assert [c.value for c in totals_sheet[1]][:3] == ["Bolla No", "Del", "N.Colli"]
    assert [c.value for c in totals_sheet[2]] == ["B1", "01/01/2026", 3.0, 1.0, 0.5, 0.25, 10, 25.5, 27.0]
