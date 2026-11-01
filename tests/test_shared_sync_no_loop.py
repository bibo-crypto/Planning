"""A shared source that fails to load must be tried once, not endlessly (the app froze when
the Situazione pages kept starting a new worker for the same big workbook)."""
import time
import tkinter as tk

import pandas as pd
import pytest

from calculate.situazione import find_price_anomalies  # noqa: F401  (import check only)
from gui.tabs import overview_tab


class _SyncThread:
    """Runs a worker at once on the calling thread (Tk accepts after() from another thread
    only inside a real mainloop)."""

    def __init__(self, target, args=(), name=None, daemon=None):
        self._target, self._args = target, args

    def start(self):
        self._target(*self._args)


def _pump(root, seconds=0.4):
    end = time.time() + seconds
    while time.time() < end:
        root.update()
        time.sleep(0.01)


@pytest.fixture()
def root():
    try:
        window = tk.Tk()
    except tk.TclError:
        pytest.skip("no display")
    yield window
    window.destroy()


def test_situazione_does_not_retry_a_failed_production_file(root, tmp_path, monkeypatch):
    from gui.tabs import situazione_sources as sources
    from gui.tabs.situazione_tab import SituazioneTab

    prod = tmp_path / "prod.xlsx"
    prod.write_text("not really a workbook", encoding="utf-8")
    calls = []
    monkeypatch.setattr(sources, "load_dfm_cache", lambda: {"source_path": ""})
    monkeypatch.setattr(sources, "load_prod_cache", lambda: {"source_path": str(prod)})
    monkeypatch.setattr(sources.data_loaders, "load_data_prod", lambda path: calls.append(path) or (None, ["unreadable"]))
    monkeypatch.setattr(sources.threading, "Thread", _SyncThread)

    tab = SituazioneTab(root)
    tab._db_restore_scheduled = tab._sources_restore_started = True
    for _ in range(6):
        tab.sync_shared_async()
        _pump(root, 0.1)
    assert len(calls) == 1                                     # one attempt, then it leaves the file alone

    other = tmp_path / "prod2.xlsx"                            # a new path is a new attempt
    other.write_text("x", encoding="utf-8")
    monkeypatch.setattr(sources, "load_prod_cache", lambda: {"source_path": str(other)})
    tab.sync_shared_async()
    _pump(root, 0.1)
    assert len(calls) == 2


def test_the_weekly_page_does_not_retry_failed_files_either(root, tmp_path, monkeypatch):
    from gui.tabs import situazione_settimana_tab as weekly

    dfm, prod = tmp_path / "dfm.xlsx", tmp_path / "prod.xlsx"
    dfm.write_text("x", encoding="utf-8")
    prod.write_text("x", encoding="utf-8")
    calls = {"dfm": 0, "prod": 0}

    def failing(kind):
        def load(path):
            calls[kind] += 1
            return None, ["unreadable"]
        return load

    monkeypatch.setattr(weekly, "load_dfm_cache", lambda: {"source_path": str(dfm)})
    monkeypatch.setattr(weekly, "load_prod_cache", lambda: {"source_path": str(prod)})
    monkeypatch.setattr(weekly.data_loaders, "load_dfm", failing("dfm"))
    monkeypatch.setattr(weekly.data_loaders, "load_produzione", failing("prod"))
    monkeypatch.setattr(weekly.threading, "Thread", _SyncThread)

    tab = weekly.SettimanaTab(root)
    for _ in range(6):
        tab.sync_shared_async()
        _pump(root, 0.1)
    assert calls == {"dfm": 1, "prod": 1}


# ---------------------------------------------------------------- the Errori Prezzo card
def test_the_errori_prezzo_card_counts_the_rows_the_window_lists():
    """3 colours on 4 machines each = 12 erroneous lines: the card must say 12, not 3."""
    rows = []
    for colour in ("790001", "790002", "790003"):
        for machine in range(4):
            rows.append({"cliente": "ELVY", "articolo": "C1", "codice": colour, "colore": colour,
                         "partita": f"{colour}{machine}", "ordine": "O", "riga": machine, "bagno": f"T{machine}",
                         "mc": 72, "prezzo": "5.0", "prezzo_lisini": "6.0"})
    anomalies, card_number = overview_tab.price_error_card(pd.DataFrame(rows))
    assert card_number == len(anomalies) == 12
    assert anomalies["codice"].nunique() == 3
