"""Regression tests for the Kamal grouping and optional order number updates."""

from pipelines.ordine_kamal import (
    OrdineKamalRow,
    assign_ordine_kamal_machines,
    build_ordine_kamal_rows,
)
from parsers.kamal_parser import KamalOrderRow


def _row(titolo: str, peso: float, coloredfm: str = "11") -> OrdineKamalRow:
    return OrdineKamalRow(coloredfm=coloredfm, titolo=titolo, peso_kg=peso)


def test_kamal_same_ply_titolo_values_are_combined_even_when_different():
    rows = [_row("50/1", 20), _row("96/1", 25)]

    assign_ordine_kamal_machines(rows)

    # Same colour and both /1: they are one 45 kg group, so both receive the
    # same machine assignment instead of two independent machines.
    assert [r.abbina for r in rows] == ["Machine 56 Cones", "Machine 56 Cones"]
    assert rows[0].macchina == rows[1].macchina


def test_kamal_odd_and_even_ply_titolo_values_never_share_machine():
    rows = [_row("50/1", 20), _row("100/2", 25)]

    assign_ordine_kamal_machines(rows)

    assert [r.abbina for r in rows] == ["Machine 24 Cones", "Machine 32 Cones"]
    assert rows[0].macchina != rows[1].macchina


def test_kamal_non_adjacent_different_titolo_stays_separate():
    rows = [_row("50/1", 20), _row("100/2", 20), _row("50/1", 20)]

    assign_ordine_kamal_machines(rows)

    # The two /1 rows share their own group, but /2 must not be merged into it.
    assert rows[0].abbina == rows[2].abbina == "Machine 56 Cones"
    assert rows[1].abbina == "Machine 24 Cones"


def test_kamal_optional_order_number_uses_requested_commento_format():
    parsed = [
        KamalOrderRow(
            reply_no="105",
            order_date="2026/07/20",
            coloredfm="11",
            titolo="50/1",
            peso_kg=10,
        )
    ]

    rows = build_ordine_kamal_rows(
        parsed,
        [{"articolo": "C1700001", "titolo": "50/1"}],
        order_no="28",
    )

    assert rows[0].commento == "PG-X-ORD.Nr.28-2026-(LETTER 105)"
    assert rows[0].order_no == "28"


def test_kamal_without_optional_order_number_keeps_legacy_commento():
    parsed = [KamalOrderRow(reply_no="105", order_date="2026/07/20")]
    rows = build_ordine_kamal_rows(parsed, [], order_no=None)
    assert rows[0].commento == "PG-X-ORD.nr.2026(LETTER 105)"
