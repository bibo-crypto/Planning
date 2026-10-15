"""Notifications carry Ordine/Riga; Smart Auto-Assign shows Codice/Colore in Situazione's order."""
from types import SimpleNamespace

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from utility import notifications
    monkeypatch.setattr(notifications, "_PATH", tmp_path / "notifications.json")
    return notifications


def test_notification_keeps_ordine_and_riga_as_readable_text(store):
    store.add("k1", "Title", "Message", "Situazione Generale", ordine="O-1234", riga=7.0)
    store.add("k2", "Title", "Message", "Situazione Generale", ordine=float("nan"), riga=None)
    store.add("k3", "Title", "Message", "Prezzi")            # producers without an order row
    by_key = {n["key"]: n for n in store.list_open()}
    assert (by_key["k1"]["ordine"], by_key["k1"]["riga"]) == ("O-1234", "7")     # 7.0 -> "7"
    assert (by_key["k2"]["ordine"], by_key["k2"]["riga"]) == ("", "")            # nan/None -> blank
    assert (by_key["k3"]["ordine"], by_key["k3"]["riga"]) == ("", "")


def test_notifications_saved_before_the_new_fields_still_load(store):
    store._write([{"key": "old", "title": "t", "message": "m", "page": "p", "created_at": "2026-01-01T00:00:00"}])
    item = store.list_all()[0]
    assert item["ordine"] == "" and item["riga"] == ""


def test_notification_table_and_export_have_ordine_and_riga_after_partita_colore():
    from gui.gui import NOTIFICATION_COLUMNS
    fields = [column[0] for column in NOTIFICATION_COLUMNS]
    assert fields.index("partita_colore") + 1 == fields.index("ordine") and fields.index("ordine") + 1 == fields.index("riga")


def test_situazione_price_notifications_carry_ordine_and_riga(monkeypatch):
    import exporters.biglietti_exporter as biglietti_exporter
    from gui.tabs.situazione_refresh import SituationRefreshMixin

    monkeypatch.setattr(biglietti_exporter, "load_prezzo_lookup", lambda: ({}, None))
    frame = pd.DataFrame([{"articolo": "C130027S", "codice": "440", "colore": "Blue", "partita": "9001",
                           "prezzo": "3.5", "mc": "", "comment": "", "ordine": "O-1234", "riga": 7.0}])
    _result, pending = SituationRefreshMixin._recompute_prezzo_densita_for_frame(SimpleNamespace(), frame)
    added = [entry for entry in pending if entry[0] == "add"]
    assert added and all(entry[-2:] == ("O-1234", 7.0) for entry in added)


def test_auto_assign_preview_columns_follow_situazione_generale_order():
    from gui.tabs.shared_order_actions import AUTO_ASSIGN_COLUMNS, AUTO_ASSIGN_HEADINGS, AUTO_ASSIGN_WIDTHS
    from gui.tabs.situazione_tab import COLUMN_SPEC

    assert {"codice", "colore"} <= set(AUTO_ASSIGN_COLUMNS)
    assert set(AUTO_ASSIGN_COLUMNS) == set(AUTO_ASSIGN_HEADINGS) == set(AUTO_ASSIGN_WIDTHS)
    situazione_order = [key for key, _header, _type in COLUMN_SPEC]
    shared = [c for c in AUTO_ASSIGN_COLUMNS if c in situazione_order]
    assert shared == sorted(shared, key=situazione_order.index)                  # cliente, articolo, codice, colore, rocche
    assert AUTO_ASSIGN_COLUMNS.index("colore") < AUTO_ASSIGN_COLUMNS.index("partita_col") < AUTO_ASSIGN_COLUMNS.index("rocche")
