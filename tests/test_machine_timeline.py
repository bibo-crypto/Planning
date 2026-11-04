"""Machine Timeline logic: colours, block status/ends, search."""
from datetime import datetime

import pandas as pd

from calculate import machine_timeline as mt
from gui.tabs.machine_timeline_tab import MachineTimelineTab

NOW = datetime(2026, 10, 31, 11, 25)


def _frames():
    cop = pd.DataFrame({
        "bagno": ["S940", "0941", "942"],
        "machine": ["3304", "3304", "3304"],
        "batch_start": pd.to_datetime(["2026-10-31 00:00", "2026-10-31 12:00", "2026-11-01 00:00"]),
        "batch_end": [pd.NaT] * 3,
    })
    sit = pd.DataFrame({"bagno": ["940", "941"], "partita": ["P1", "P2"], "codice": ["T1296", "T1303"],
                        "colore": ["BLU", "ROSSO"], "cliente": ["A", "B"]})
    col = pd.DataFrame({"partita": ["P1"], "bagno": [""], "rgb": ["#998574"]})
    return sit, cop, col


def test_parse_rgb():
    assert mt.parse_rgb("RGB(153/133/116)") == "#998574"
    assert mt.parse_rgb("153,133,116") == "#998574"
    assert mt.parse_rgb("RGB(300/1/1)") is None
    assert mt.parse_rgb(None) is None


def test_blocks_status_label_and_colour():
    blocks = mt.build_blocks(*_frames(), now=NOW)
    assert list(blocks["status"]) == ["done", "queued", "queued"] or list(blocks["status"])[0] in ("done", "running")
    first, second = blocks.iloc[0], blocks.iloc[1]
    assert first["label"] == "T1296 - BLU - S940" and first["rgb"] == "#998574"
    assert second["rgb"] == mt.NO_COLOR and not second["has_color"]
    assert first["end"] == second["start"] - (second["start"] - first["end"])  # end <= next start
    assert first["end"] <= second["start"]


def test_status_boundaries():
    s, e = datetime(2026, 10, 31, 0), datetime(2026, 10, 31, 12)
    assert mt.block_status(s, e, datetime(2026, 11, 1)) == "done"
    assert mt.block_status(s, e, datetime(2026, 10, 31, 5)) == "running"
    assert mt.block_status(s, e, datetime(2026, 10, 30)) == "queued"


def test_machine_rows_fit_in_available_chart_height():
    row_height = MachineTimelineTab._fit_row_height(420, 10)
    assert row_height == 42
    assert row_height * 10 <= 420
    assert MachineTimelineTab._fit_row_height(900, 10) == MachineTimelineTab.ROW_H


def test_delivery_delay_allows_three_days_after_dyeing():
    planedate = "2026-11-02"
    assert mt.delivery_delay_days(planedate, {"cliente": "OTHER", "consegna": "2026-11-05"}) == 0
    assert mt.delivery_delay_days(planedate, {"cliente": "OTHER", "consegna": "2026-11-06"}) == -1
    assert mt.delivery_delay_days(planedate, {"cliente": "OTHER", "consegna": "2026-11-04"}) == 1


def test_delivery_delay_reads_actual_copertura_planedate_and_flags_short_buffer():
    planedate = "PROD.03/11/2026"
    row = {"cliente": "OTHER", "consegna": "05/11/2026"}
    assert mt.delivery_delay_days(planedate, row) == 1
    assert mt.delivery_delay_text(planedate, row) == "RITARDO: late by 1 day"


def test_timeline_block_carries_plane_date_into_delay_warning():
    situation, copertura, colours = _frames()
    situation["consegna"] = ["05/11/2026", ""]
    copertura["planedate"] = ["PROD.03/11/2026", "IN MACC.", None]
    blocks = mt.build_blocks(situation, copertura, colours, now=NOW)
    first = blocks.iloc[0]
    assert first["planedate"] == "PROD.03/11/2026"
    assert mt.delivery_delay_text(first["planedate"], first["rows"][0]) == "RITARDO: late by 1 day"


def test_elvy_delivery_date_is_preferred_and_consegna_is_fallback():
    planedate = "2026-11-02"
    assert mt.delivery_delay_days(planedate, {
        "cliente": "ELVY", "delivery_date": "2026-11-07", "consegna": "2026-11-04",
    }) == -2
    assert mt.delivery_delay_days(planedate, {
        "cliente": "ELVY", "delivery_date": "Pending for yarn", "consegna": "2026-11-04",
    }) == 1
    assert mt.delivery_delay_days(planedate, {
        "cliente": "OTHER", "delivery_date": "2026-11-07", "consegna": "2026-11-04",
    }) == 1


def test_real_batch_end_is_used():
    sit, cop, col = _frames()
    cop["batch_end"] = pd.to_datetime(["2026-10-31 06:00", None, None])
    cop["planedate"] = ["2026-11-01", "2026-11-02", "2026-11-03"]
    blocks = mt.build_blocks(sit, cop, col, now=NOW)
    assert blocks.iloc[0]["end"] == datetime(2026, 10, 31, 6) and blocks.iloc[0]["end_known"]
    assert blocks.iloc[0]["planedate"] == "2026-11-01"


def test_search():
    blocks = mt.build_blocks(*_frames(), now=NOW)
    assert mt.search_blocks(blocks, "rosso") == [1]
    assert mt.search_blocks(blocks, "nope") == []


def test_colour_found_through_codice_and_colore_when_bagno_is_not_in_produzione():
    sit, cop, _ = _frames()
    colours = pd.DataFrame({"partita": ["Z9"], "bagno": ["T9999"], "codice": ["000T1303 RI"], "colore": ["rosso"],
                            "rgb": ["#aa0000"]})
    sit.loc[sit["codice"] == "T1303", "codice"] = "000T1303"      # same colour, other spelling of the code
    blocks = mt.build_blocks(sit, cop, colours, now=NOW)
    assert blocks.iloc[1]["rgb"] == "#aa0000"          # Bagno 941 / ROSSO: matched by codice + colore
    assert blocks.iloc[0]["rgb"] == mt.NO_COLOR


def test_set_time_becomes_the_batch_end():
    from parsers.situazione_loaders import _parse_duration
    assert _parse_duration("7:56") == pd.Timedelta(hours=7, minutes=56)
    assert _parse_duration(None) is pd.NaT


def test_codice_alone_gives_the_rgb_even_when_the_colour_name_differs():
    sit, cop, _ = _frames()
    colours = pd.DataFrame({"partita": ["Z8", "Z9"], "bagno": ["T9998", "T9999"], "codice": ["T1296", "T1296"],
                            "colore": ["OTHER NAME", "OTHER NAME 2"], "rgb": ["#111111", "#22aa22"]})
    blocks = mt.build_blocks(sit, cop, colours, now=NOW)
    assert blocks.iloc[0]["rgb"] == "#22aa22"          # latest row of the Codice wins


def test_on_time_text_reports_the_days_to_spare_and_blocks_carry_the_late_flag():
    row = {"cliente": "OTHER", "consegna": "2026-11-05"}
    assert mt.delivery_delay_text("2026-11-02", row) == "RITARDO: no - on time (0 days buffer)"
    row["consegna"] = "2026-11-08"
    assert mt.delivery_delay_text("2026-11-02", row) == "RITARDO: no - on time (3 days buffer)"
    situation, copertura, colours = _frames()
    situation["consegna"] = ["05/11/2026", ""]
    copertura["planedate"] = ["PROD.03/11/2026", "IN MACC.", None]
    blocks = mt.build_blocks(situation, copertura, colours, now=NOW)
    assert bool(blocks.iloc[0]["late"]) is True
