"""Characterization tests for calculate/magazino.py.

They pin the behaviour of the raw-yarn warehouse loader as it is today (header row
search, repeated header row, padded ERP strings with decimal commas, warehouse /
prefix / "used up" / zero-colli filters, grouping by Articolo AND Partita) so that
later refactoring cannot change a stock figure silently.  The data is synthetic but
has the same shape as the real MAGAZINO export.
"""
import pandas as pd
import pytest

from calculate import magazino
from utility import disk_cache

DETAIL_HEADER = ["DITTA", "MAGAZZINO", "ARTICOLO", "COLORE", "PARTITA", "BAGNO", "CONFEZIONE",
                 "ORDINE", "UM", "ESISTENZA", "COLLI", "SALDO", "DESCRIZIONE ART"]


def _write(path, rows):
    pd.DataFrame(rows).to_excel(path, header=False, index=False)
    return path


def _detail_file(tmp_path):
    rows = [
        DETAIL_HEADER,
        DETAIL_HEADER,  # the ERP export repeats the header row
        ["60", 900160, "G130001S", "7777", "140849", "GN    ", "RS", 901031, "KG", "        23,00", "    25,0   ", " ", "0020  038.00 3    "],
        ["60", 900160, "G130002S", "7777", "140850", "GN    ", "RS", 0, "KG", "10,0", "2", " ", "used up"],
        ["60", 900910, "G170003S", "7777", "150001", "GN    ", "RS", 0, "KG", "5,5", "3", " ", "kept: 900910 is never 'used up'"],
        ["60", 900999, "G130004S", "7777", "150002", "GN    ", "RS", 5, "KG", "9,0", "4", " ", "other warehouse"],
        ["60", 900160, "C010005S", "7777", "150003", "GN    ", "RS", 5, "KG", "8,0", "6", " ", "not a raw yarn prefix"],
        ["60", 900160, "G130006S", "7777", "150004", "GN    ", "RS", 7, "KG", "1,0", "0", " ", "zero colli"],
    ]
    return _write(tmp_path / "MAGAZINO.xlsx", rows)


def test_detailed_layout_applies_every_filter_and_cleans_the_padded_values(tmp_path):
    df, errors = magazino._load_magazino_uncached(_detail_file(tmp_path))
    assert errors == []
    assert list(df.columns) == ["articolo", "titolo", "partita", "ordine", "esistenza", "colli", "magazzino"]
    assert df["articolo"].tolist() == ["G130001S", "G170003S"]
    assert df["partita"].tolist() == ["140849", "150001"]
    assert df["esistenza"].tolist() == [23.0, 5.5]          # '        23,00' -> 23.0 (decimal comma)
    assert df["colli"].tolist() == [25.0, 3.0]
    assert df["magazzino"].tolist() == [900160, 900910]
    assert df["titolo"].iloc[0] == "0020  038.00 3"            # stripped at the ends only


def test_prefix_none_keeps_every_articolo_but_still_filters_warehouse_used_up_and_zero_colli(tmp_path):
    df, errors = magazino._load_magazino_uncached(_detail_file(tmp_path), articolo_prefix=None)
    assert errors == []
    assert df["articolo"].tolist() == ["G130001S", "G170003S", "C010005S"]


def test_a_single_prefix_string_is_accepted(tmp_path):
    df, _ = magazino._load_magazino_uncached(_detail_file(tmp_path), articolo_prefix="G170")
    assert df["articolo"].tolist() == ["G170003S"]


def test_missing_header_row_returns_none_and_a_message(tmp_path):
    path = _write(tmp_path / "bad.xlsx", [["foo", "bar"], [1, 2]])
    df, errors = magazino._load_magazino_uncached(path)
    assert df is None
    assert errors and "header row" in errors[0]


def test_summary_layout_is_returned_straight_away(tmp_path):
    rows = [
        ["Articolo", "Partita", "Mag.rocche", "Mag.peso", "Descrizione Art"],
        ["G130001S", "P1", "10", "25,5", "Titolo uno"],
        ["G130002S", "  ", "1", "1", "no partita"],
        ["C010009S", "P9", "1", "1", "other prefix"],
    ]
    df, errors = magazino._load_magazino_uncached(_write(tmp_path / "summary.xlsx", rows))
    assert errors == []
    assert df.to_dict("records") == [
        {"articolo": "G130001S", "titolo": "Titolo uno", "partita": "P1", "mag_rocche": 10.0, "mag_peso": 25.5}
    ]


def test_summarize_by_partita_groups_by_articolo_and_partita_not_by_partita_alone():
    frame = pd.DataFrame({
        "articolo": ["B", "A", "A"], "titolo": ["u", "t", "t"], "partita": ["P1", "P1", "P1"],
        "colli": [5, 1, 3], "esistenza": [6.0, 2.0, 4.0],
    })
    out = magazino.summarize_by_partita(frame)
    assert out.to_dict("records") == [
        {"articolo": "A", "titolo": "t", "partita": "P1", "mag_rocche": 4, "mag_peso": 6.0},
        {"articolo": "B", "titolo": "u", "partita": "P1", "mag_rocche": 5, "mag_peso": 6.0},
    ]


def test_summarize_by_partita_of_nothing_is_an_empty_frame_with_the_standard_columns():
    for empty in (None, pd.DataFrame()):
        out = magazino.summarize_by_partita(empty)
        assert out.empty
        assert list(out.columns) == ["articolo", "titolo", "partita", "mag_rocche", "mag_peso"]


def test_load_magazino_goes_through_the_cache_and_reloads_when_the_file_changes(tmp_path, monkeypatch):
    monkeypatch.setattr(disk_cache, "_cache_dir", lambda: tmp_path / "cache")
    (tmp_path / "cache").mkdir()
    disk_cache._MEMORY_CACHE.clear()
    path = _detail_file(tmp_path)
    calls = []
    original = magazino._load_magazino_uncached
    monkeypatch.setattr(magazino, "_load_magazino_uncached", lambda *a, **k: calls.append(1) or original(*a, **k))
    first, _ = magazino.load_magazino(path)
    second, _ = magazino.load_magazino(path)
    assert len(calls) == 1 and first.equals(second)
    disk_cache._MEMORY_CACHE.clear()
