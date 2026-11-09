"""One CONSEGNA rule for ELVY, MED and EL KAMAL (calculate/consegna.py).

A colour queued on a machine is delivered 14 days after the machine's coverage (two colours a
day, no Fridays); a row without a machine is delivered 14 days from today.  Ordine MED always
worked like that; ELVY and Kamal used a flat "today + 14".  The rule is exercised on its own
and end to end through the three Ordine pages.
"""
import datetime as dt
import time
from types import SimpleNamespace
from unittest.mock import patch

import openpyxl
import pytest

from calculate import situazione
from calculate.abbina_calculator import MACHINE_CODES
from calculate.consegna import CONSEGNA_LEAD_DAYS, ConsegnaPlanner, apply_order_consegna
from pipelines.ordine_kamal import OrdineKamalRow
from pipelines.ordini_elvy import OrdiniElvyRow, build_ordini_elvy_rows
from tests.test_elvy_conversion_prezzi import harness  # noqa: F401  (a fixture)
from tests.test_elvy_lot import _po_row
from tests.test_first_bagno_elvy_kamal import root  # noqa: F401  (a fixture)

MONDAY = dt.date(2026, 11, 9)
THURSDAY = dt.date(2026, 11, 12)


def test_the_lead_time_is_fourteen_days():
    assert CONSEGNA_LEAD_DAYS == 14


def test_a_row_without_a_machine_is_delivered_fourteen_days_from_today():
    planner = ConsegnaPlanner({}, today=MONDAY)
    assert planner.base_date(None) == dt.date(2026, 11, 23)
    assert planner.base_date("") == dt.date(2026, 11, 23)
    assert planner.base_date("not a machine") == dt.date(2026, 11, 23)       # unreadable label: no machine


def test_colours_on_one_machine_step_forward_two_per_day():
    planner = ConsegnaPlanner({}, today=MONDAY)
    dates = [planner.base_date(3308) for _ in range(5)]
    # 1-2 colours: Monday, 3-4: Tuesday, 5: Wednesday -- each +14 days
    assert dates == [dt.date(2026, 11, 23), dt.date(2026, 11, 23), dt.date(2026, 11, 24),
                     dt.date(2026, 11, 24), dt.date(2026, 11, 25)]


def test_fridays_do_not_count_as_production_days():
    planner = ConsegnaPlanner({5: 2}, today=THURSDAY)            # two colours already queued on machine 5
    # the third colour needs a second day: Thursday is the first, Friday is skipped, Saturday the second
    assert planner.base_date("3308") == dt.date(2026, 11, 14) + dt.timedelta(days=14)


def test_the_overview_baseline_is_part_of_the_queue():
    assert ConsegnaPlanner({5: 8}, today=MONDAY).base_date(3308) == dt.date(2026, 11, 14) + dt.timedelta(days=14)


def test_every_machine_has_its_own_queue():
    planner = ConsegnaPlanner({}, today=MONDAY)
    first = [planner.base_date(3308), planner.base_date(3306), planner.base_date(3308), planner.base_date(3308)]
    assert first == [dt.date(2026, 11, 23), dt.date(2026, 11, 23), dt.date(2026, 11, 23), dt.date(2026, 11, 24)]


def test_apply_order_consegna_sets_midnight_dates_and_the_day_before_for_riconsegna():
    rows = [OrdineKamalRow(macchina=3308), OrdineKamalRow(macchina=None), OrdineKamalRow(macchina=3308)]
    apply_order_consegna(rows, {}, today=MONDAY)
    assert [r.data_consegna for r in rows] == [dt.datetime(2026, 11, 23), dt.datetime(2026, 11, 23), dt.datetime(2026, 11, 23)]
    assert [r.data_riconsegna for r in rows] == [dt.datetime(2026, 11, 22)] * 3
    apply_order_consegna(rows, {5: 20}, today=MONDAY)             # a long queue pushes it out; no-machine row stays
    assert rows[0].data_consegna > dt.datetime(2026, 11, 23) and rows[1].data_consegna == dt.datetime(2026, 11, 23)


# ------------------------------------------------------------------------------ ELVY builder
@pytest.fixture()
def coverage_by_count(monkeypatch):
    """Deterministic coverage: N colours queued -> 2026-12-<N>."""
    monkeypatch.setattr(situazione, "machine_coverage_until", lambda count: f"2026-12-{int(count):02d}")


def _elvy_orders(count):
    rows = [_po_row("", pos=10 * (i + 1), colour=f"C{i}", coloredfm=str(100 + i), abbina="Machine 72 Cones") for i in range(count)]
    return rows


def test_the_elvy_builder_is_unchanged_without_machine_totals():
    out = build_ordini_elvy_rows(_elvy_orders(3))
    expected = dt.datetime.now().replace(hour=0, minute=0, second=0, microsecond=0) + dt.timedelta(days=14)
    assert {r.data_consegna for r in out} == {expected}


def test_the_elvy_builder_follows_machine_coverage_when_totals_are_given(coverage_by_count):
    out = build_ordini_elvy_rows(_elvy_orders(3), machine_totals={})
    assert [r.macchina for r in out] == [MACHINE_CODES[72]] * 3
    assert [r.data_consegna for r in out] == [dt.datetime(2026, 12, n) + dt.timedelta(days=14) for n in (1, 2, 3)]
    assert [r.data_riconsegna for r in out] == [dt.datetime(2026, 12, n) + dt.timedelta(days=13) for n in (1, 2, 3)]


# ------------------------------------------------------------- the three Ordine pages, end to end
def _consegna_by_machine_queue(machine_codes, baseline=0):
    """CONSEGNA the rule gives, derived independently from the machine column of the file itself."""
    seen, out = {}, []
    for code in machine_codes:
        number = situazione.machine_number_from_label(str(code))
        seen[number] = seen.get(number, 0) + 1
        out.append(dt.datetime(2026, 12, baseline + seen[number]) + dt.timedelta(days=14))
    return out


def _column(ws, name):
    header = [c.value for c in ws[1]]
    return [ws.cell(r, header.index(name) + 1).value for r in range(2, ws.max_row + 1)]


def test_ordine_elvy_page_sends_the_machine_coverage_to_the_workbook_and_the_erp_file(harness, tmp_path, coverage_by_count):  # noqa: F811
    ui, root_window = harness
    erp_dir = tmp_path / "erp"
    erp_dir.mkdir()
    ui._run_po_conversion([tmp_path / "a.pdf", tmp_path / "b.pdf"], tmp_path, False, True, False, erp_dir, None,
                          machine_totals={})
    for _ in range(20):
        root_window.update()
        time.sleep(0.01)
    assert ui.done == ([], 2)
    erp = openpyxl.load_workbook(erp_dir / "EXCEL PER ORDINE VENDITA EGITTO.xlsx")["Foglio1"]
    machines = _column(erp, "GRUPPO MACCHINA")
    expected = _consegna_by_machine_queue(machines)
    assert _column(erp, "CONSEGNA") == expected
    assert _column(erp, "DATA RICONSEGNA") == [d - dt.timedelta(days=1) for d in expected]
    # the "Ordini ELVY" sheet of the order workbook shows the very same dates
    sheet = openpyxl.load_workbook(tmp_path / "Ordine_Elvy.xlsx")["Ordini ELVY"]
    assert _column(sheet, "CONSEGNA") == expected


def test_ordine_elvy_page_reads_the_overview_on_the_ui_thread_and_survives_a_failure(monkeypatch):
    import inspect

    from gui.workflows import purchase_orders

    source = inspect.getsource(purchase_orders.PurchaseOrderWorkflowMixin)
    assert "machine_totals_for_med()" in source and "machine_totals," in source   # read before the worker starts
    assert source.count("machine_totals=machine_totals") >= 3                      # both exporters + the ERP rows


def _kamal_tab(root_window, monkeypatch, provider=None):
    from gui.tabs import kamal_tab

    monkeypatch.setattr(kamal_tab, "load_settings", lambda: {})
    monkeypatch.setattr(kamal_tab, "save_settings", lambda prefs: None)
    return kamal_tab, kamal_tab.KamalTab(root_window, machine_totals_provider=provider)


def test_kamal_tab_takes_the_machine_totals_when_convert_is_pressed(root, monkeypatch, tmp_path):  # noqa: F811
    kamal_tab, tab = _kamal_tab(root, monkeypatch, provider=lambda: {5: 3})
    tab._pdf_paths, tab._output_path, tab._shared_dfm_path = [tmp_path / "x.pdf"], tmp_path / "o.xlsx", "dfm"
    with patch.object(kamal_tab.threading, "Thread") as thread:
        tab._on_convert()
    assert thread.called and tab._machine_totals_snapshot == {5: 3}


def test_kamal_tab_converts_even_when_the_overview_cannot_be_read(root, monkeypatch, tmp_path):  # noqa: F811
    def broken():
        raise RuntimeError("no schedule")

    kamal_tab, tab = _kamal_tab(root, monkeypatch, provider=broken)
    tab._pdf_paths, tab._output_path, tab._shared_dfm_path = [tmp_path / "x.pdf"], tmp_path / "o.xlsx", "dfm"
    with patch.object(kamal_tab.threading, "Thread") as thread:
        tab._on_convert()
    assert thread.called and tab._machine_totals_snapshot == {}


def test_kamal_conversion_writes_machine_coverage_dates_in_the_workbook_and_the_erp_file(root, monkeypatch, tmp_path, coverage_by_count):  # noqa: F811
    import pandas as pd

    from parsers.kamal_parser import KamalOrderRow

    kamal_tab, tab = _kamal_tab(root, monkeypatch)
    rows = [KamalOrderRow(reply_no="98", order_date="2026/07/20", sender_msg_no="MSG1", coloredfm="11", peso_kg=10),
            KamalOrderRow(reply_no="98", order_date="2026/07/20", sender_msg_no="MSG1", coloredfm="12", peso_kg=5)]
    monkeypatch.setattr(kamal_tab, "KamalParser", lambda path: SimpleNamespace(parse=lambda: rows))
    monkeypatch.setattr(kamal_tab, "load_dfm_entries_by_prefix", lambda prefix: [{"articolo": "C1700001", "titolo": "80/2"}])
    stock = pd.DataFrame([{"articolo": "G1700001", "titolo": "80/2", "partita": "777", "mag_rocche": 50, "mag_peso": 500.0}])
    monkeypatch.setattr(kamal_tab.magazino_logic, "load_magazino_snapshot", lambda prefix=None: (stock, []))
    monkeypatch.setattr(kamal_tab.lotti_logic, "load_lotti_snapshot", lambda prefix=None: (pd.DataFrame(), []))
    erp_dir, filato_dir = tmp_path / "erp", tmp_path / "filato"
    erp_dir.mkdir()
    filato_dir.mkdir()
    tab._pdf_paths, tab._output_path = [tmp_path / "x.pdf"], tmp_path / "Ordine_Kamal.xlsx"
    tab._kamal_erp_export_dir, tab._kamal_filato_export_dir = erp_dir, filato_dir
    tab._machine_totals_snapshot = {}
    tab.after = lambda *a, **k: None
    tab._set_status = lambda text: None
    tab._run_conversion()

    erp = openpyxl.load_workbook(erp_dir / "EXCEL PER ORDINE VENDITA EGITTO.xlsx")["Foglio1"]
    expected = _consegna_by_machine_queue(_column(erp, "GRUPPO MACCHINA"))
    assert _column(erp, "CONSEGNA") == expected
    sheet = openpyxl.load_workbook(tmp_path / "Ordine_Kamal.xlsx")["Ordine Kamal"]
    assert _column(sheet, "CONSEGNA") == expected


def test_a_kamal_conversion_without_machine_totals_keeps_today_plus_fourteen(root, monkeypatch, tmp_path):  # noqa: F811
    kamal_tab, tab = _kamal_tab(root, monkeypatch)
    assert tab._machine_totals_snapshot is None          # nothing taken yet -> the exporters keep the flat rule
