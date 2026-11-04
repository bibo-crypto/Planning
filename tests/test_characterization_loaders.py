"""Characterization tests for parsers/situazione_loaders.py (18% covered before).

Every ERP export is read with the header row searched for (it can sit below a title row
and is often repeated), padded strings are stripped, and each loader applies its own
business filter.  The workbooks are synthetic but follow the shape of the real exports.
"""
import datetime as dt

import pandas as pd

from calculate.machine_timeline import parse_rgb
from parsers import situazione_loaders as loaders


def _write(path, rows):
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


def test_wincoint_drops_totals_blank_and_repeated_rows_and_reads_codice_colore_by_position(tmp_path):
    header = ["Cliente", "c2", "Articolo", "c4", "c5", "Codice", "Colore", "Ordine", "Riga", "Data",
              "Consegna", "Partita", "Ordinata", "Descrizione aggiuntiva ordine", "Bagno", "Prezzo"]
    rows = [
        ["Title row"],
        header,
        ["MED", "", "C010118S", "", "", "344", "MAKO", "0/005314", 3, "2026-07-28", "2026-08-30",
         "P100", 100, "note", "B1", "USD 5,11"],
        ["TOTALE GENERALE", "", "", "", "", "", "", "", "", "", "", "P101", 1, "", "", ""],
        ["MED", "", "C0", "", "", "1", "X", "", "", "", "", "  ", 1, "", "", ""],
        ["MED", "", "C0", "", "", "1", "X", "", "", "", "", "Partita", 1, "", "", ""],
    ]
    out, errors = loaders.load_wincoint_orders(_write(tmp_path / "w.xlsx", rows))
    assert errors == []
    assert len(out) == 1
    row = out.iloc[0]
    assert (row["cliente"], row["articolo"], row["codice"], row["colore"]) == ("MED", "C010118S", "344", "MAKO")
    assert (row["ordine"], row["riga"], row["partita"], row["cq"], row["prezzo"]) == ("0/005314", "3", "P100", "B1", "USD 5,11")
    assert row["data"] == pd.Timestamp("2026-07-28") and row["consegna"] == pd.Timestamp("2026-08-30")
    assert row["rocche"] == 100 and row["comment"] == "note"


def test_wincoint_without_the_expected_columns_reports_the_problem(tmp_path):
    out, errors = loaders.load_wincoint_orders(_write(tmp_path / "w.xlsx", [["a", "b"], [1, 2]]))
    assert out is None and errors and "header row" in errors[0]


def test_dfm_splits_the_machine_number_and_sorts_by_partita(tmp_path):
    header = ["DESCRIZIONECDMACCHINA", "PARTITADFM", "NUMEROPROGRAMMANEWDFM", "ARTICOLODFM"]
    rows = [header, header, ["3301 6 Cones Delta Dyeing", "P2", "1001", "C1"], ["3305 X", "P1", "1002", "C2"]]
    out, errors = loaders.load_dfm(_write(tmp_path / "dfm.xlsx", rows))
    assert errors == []
    assert out["partita"].tolist() == ["P1", "P2"]
    assert out["mc"].tolist() == [3305, 3301]
    assert out["bagno"].tolist() == ["1002", "1001"]


def test_data_prod_skips_prova_and_reworks_and_keeps_the_first_end_date_per_partita(tmp_path):
    rows = [
        ["Partia Col", "End", "Rilavorazione"],
        ["P1", "12.03.2026 10:00", 0],
        ["P1", "13.03.2026 09:00", 0],
        ["PROVA", "01.01.2026 00:00", 0],
        ["P2", "14.03.2026 08:00", 1],
    ]
    out, errors = loaders.load_data_prod(_write(tmp_path / "dp.xlsx", rows))
    assert errors == []
    assert out.to_dict("records") == [{"partita": "P1", "end_prod": "12/03/2026"}]


def test_schedulato_plans_dates_skipping_fridays_and_derives_the_batch_end_from_the_set_time(tmp_path):
    thursday = dt.datetime(2026, 10, 8, 1, 0)
    rows = [["N. Bagno", "Machine", "Batch Start", "Set time (HH:MM)"]]
    for index in range(5):
        rows.append([f"B{index}", "3305", thursday + dt.timedelta(hours=index), "0:41" if index == 0 else "1:30"])
    rows.append(["ALONE", "3301", thursday, None])
    out, errors = loaders.load_schedulato(_write(tmp_path / "cop.xlsx", rows))
    assert errors == []
    plan = dict(zip(out["bagno"], out["planedate"]))
    assert plan == {
        "ALONE": "IN MACC.",
        "B0": "IN MACC.",
        "B1": "PROD.08/10/2026",
        "B2": "PROD.10/10/2026",     # crosses Friday 9 Oct -> pushed one day
        "B3": "PROD.10/10/2026",
        "B4": "PROD.11/10/2026",
    }
    first = out[out["bagno"] == "B0"].iloc[0]
    assert first["machine"] == "3305"
    assert first["batch_end"] == thursday + pd.Timedelta(minutes=41)
    assert pd.isna(out[out["bagno"] == "ALONE"].iloc[0]["batch_end"])


def test_parse_duration_accepts_text_times_numbers_and_rejects_garbage():
    assert loaders._parse_duration("7:56") == pd.Timedelta(hours=7, minutes=56)
    assert loaders._parse_duration("1:02:03") == pd.Timedelta(hours=1, minutes=2, seconds=3)
    assert loaders._parse_duration(dt.time(2, 30)) == pd.Timedelta(hours=2, minutes=30)
    assert loaders._parse_duration(0.5) == pd.Timedelta(days=0.5)
    assert loaders._parse_duration(3) == pd.Timedelta(hours=3)
    assert loaders._parse_duration(None) is pd.NaT
    assert loaders._parse_duration("soon") is pd.NaT


def test_uscita_keeps_only_the_customer_warehouses_and_the_first_exit_per_partita(tmp_path):
    rows = [
        ["Partita", "Bagno", "Data Mandato", "Contro Magazzino"],
        ["P1", "B", "2026-01-12", 3004],
        ["P1", "B", "2026-01-15", 3004],
        ["P2", "B", "2026-02-01", "3009"],
        ["P3", "B", "2026-02-02", 9999],
        ["P4", "B", "not a date", 3004],
    ]
    out, errors = loaders.load_uscita(_write(tmp_path / "us.xlsx", rows))
    assert errors == []
    assert dict(zip(out["partita"], out["data_uscita"])) == {
        "P1": pd.Timestamp("2026-01-12"), "P2": pd.Timestamp("2026-02-01"),
    }


def test_qualita_keeps_the_earliest_check_date_per_partita(tmp_path):
    rows = [["Partita", "Bagno", "Data Mandato"], ["P1", "B", "2026-03-05"], ["P1", "B", "2026-03-01"]]
    out, errors = loaders.load_qualita(_write(tmp_path / "q.xlsx", rows))
    assert errors == []
    assert out["data_qualita"].tolist() == [pd.Timestamp("2026-03-01")]


def test_codes_are_stripped_and_deduplicated_on_the_first_title(tmp_path):
    rows = [["Articolo Filato", "TITOLO"], [" C1 ", "24/1"], ["C1", "30/1"], ["C2", "20/1"]]
    out, errors = loaders.load_codes(_write(tmp_path / "codes.xlsx", rows))
    assert errors == []
    assert out.to_dict("records") == [
        {"articolo_filato": "C1", "titolo": "24/1"}, {"articolo_filato": "C2", "titolo": "20/1"},
    ]


def test_produzione_excludes_reworks_and_computes_the_iso_week(tmp_path):
    rows = [
        ["Machine Name", "Partia Col", "Peso", "Codice", "End"],
        ["MC06", "P1", 362, "L01773", "12/03/2026 10:00"],
        ["MC06", "P2", 50, "437RI", "12/03/2026 10:00"],
        ["MC10", "P3", 10, "X1T.C", "12/03/2026 10:00"],
        ["MC10", "P4", "abc", "437", "13/03/2026 10:00"],
    ]
    out, errors = loaders.load_produzione(_write(tmp_path / "prod.xlsx", rows))
    assert errors == []
    assert out["partita"].tolist() == ["P1", "P4"]
    assert out["peso"].iloc[0] == 362 and pd.isna(out["peso"].iloc[1])
    assert out["sheet_date"].iloc[0] == pd.Timestamp("2026-03-12 10:00")   # dd/mm/yyyy, day first
    assert int(out["week_of_year"].iloc[0]) == 11


def test_produzione_prefers_sheet_date_and_reports_a_missing_date_column(tmp_path):
    base = ["Machine Name", "Partia Col", "Peso", "Codice"]
    out, errors = loaders.load_produzione(_write(tmp_path / "a.xlsx", [base + ["Sheet Date"], ["MC", "P1", 1, "C", "01/04/2026"]]))
    assert errors == [] and out["sheet_date"].iloc[0] == pd.Timestamp("2026-04-01")
    out, errors = loaders.load_produzione(_write(tmp_path / "b.xlsx", [base, ["MC", "P1", 1, "C"]]))
    assert out is None and errors == ["Expected a production date column named End or Sheet Date"]


def test_produzione_colors_orders_oldest_first_and_drops_rows_without_a_colour(tmp_path):
    rows = [
        ["Partia Col", "Bagno", "Codice", "Des.Colore", "Color RGB", "Start"],
        ["P1", "B1", "C1", "ROSSO", "RGB(1/1/1)", "02.03.2026"],
        ["P1", "B1", "C1", "ROSSO", "RGB(2/2/2)", "01.03.2026"],
        ["P2", "B2", "C2", "BLU", "no colour here", "03.03.2026"],
    ]
    out, errors = loaders.load_produzione_colors(_write(tmp_path / "pc.xlsx", rows))
    assert errors == []
    assert out["rgb"].tolist() == [parse_rgb("RGB(2/2/2)"), parse_rgb("RGB(1/1/1)")]
    assert out["partita"].tolist() == ["P1", "P1"]
    assert list(out.columns) == ["partita", "bagno", "codice", "colore", "rgb"]
