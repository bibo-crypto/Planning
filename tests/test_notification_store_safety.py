"""The notifications file must never lose its history because of a failed read, and the price refresh must
never save the result of a half-failed check.  Each test reproduces a scenario that was shown to go wrong
before (a 40-entry store became 1 entry; a failing second Listini load saved false alerts)."""
import json
import threading

import pandas as pd
import pytest


@pytest.fixture
def store(tmp_path, monkeypatch):
    from utility import notifications
    monkeypatch.setattr(notifications, "_PATH", tmp_path / "notifications.json")
    return notifications


def _history(count=40):
    return [{"key": f"old-{i}", "title": "t", "message": "m", "page": "p", "status": "open",
             "resolved": i % 2 == 0} for i in range(count)]


def _corrupt_copies(tmp_path):
    return sorted(tmp_path.glob("notifications.corrupt-*.json"))


# ------------------------------------------------------------------ the store itself
def test_a_missing_file_is_just_an_empty_list_and_the_first_add_creates_it(store, tmp_path):
    assert store.list_open() == []
    assert store.add("k", "T", "M", "System") is True
    assert [n["key"] for n in store.list_open()] == ["k"] and _corrupt_copies(tmp_path) == []


def test_a_corrupt_file_is_set_aside_intact_before_a_new_list_is_started(store, tmp_path):
    good = json.dumps(_history())
    broken = good[:-30]                                       # truncated -> invalid JSON
    store._PATH.write_text(broken, encoding="utf-8")

    store.add("new-alert", "New", "M", "System")

    copies = _corrupt_copies(tmp_path)
    assert len(copies) == 1 and copies[0].read_text(encoding="utf-8") == broken     # nothing lost
    assert [n["key"] for n in store.list_open()] == ["new-alert"]


def test_valid_json_that_is_not_a_list_is_also_kept_not_destroyed(store, tmp_path):
    store._PATH.write_text('{"unexpected": true}', encoding="utf-8")
    store.add("k", "T", "M", "System")
    assert _corrupt_copies(tmp_path)[0].read_text(encoding="utf-8") == '{"unexpected": true}'


def test_a_read_error_stops_every_writer_and_leaves_the_file_untouched(store, tmp_path, monkeypatch):
    original = json.dumps(_history())
    store._PATH.write_text(original, encoding="utf-8")
    real_read_text = type(store._PATH).read_text

    def locked(self, *args, **kwargs):
        if self == store._PATH:
            raise PermissionError("locked by another program")
        return real_read_text(self, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(type(store._PATH), "read_text", locked)
        for call in (lambda: store.add("k", "T", "M", "System"),
                     lambda: store.add_many([{"key": "k", "title": "T", "message": "M"}]),
                     lambda: store.resolve_missing("old-", []),
                     lambda: store.resolve("old-1"),
                     lambda: store.snooze("old-1")):
            with pytest.raises(store.NotificationStoreError):
                call()
        assert store.list_open() == []                       # a reader just sees nothing for now ...
    assert store._PATH.read_text(encoding="utf-8") == original   # ... and the history is intact
    assert _corrupt_copies(tmp_path) == []


def test_normal_operations_are_unchanged(store):
    store.add("a", "T", "M", "System")
    store.add("b", "T", "M", "System")
    store.resolve("a")
    assert [n["key"] for n in store.list_open()] == ["b"]
    assert store.resolve_missing("b", []) == 1 and store.list_open() == []


def test_the_ui_adders_log_and_do_not_raise_when_the_store_is_unavailable(monkeypatch, caplog):
    from gui import gui as gui_module
    from utility import notifications

    def boom(*_a, **_k):
        raise notifications.NotificationStoreError("locked")

    monkeypatch.setattr(notifications, "add", boom)
    monkeypatch.setattr(notifications, "add_many", boom)

    class Stub:
        def after(self, _ms, callback, *args):
            callback(*args)
        badge = 0
        def _refresh_notification_badge(self):
            self.badge += 1

    stub = Stub()
    with caplog.at_level("WARNING", logger="converter"):
        gui_module.ConverterApp._add_notification(stub, "k", "T", "M", "System")
        gui_module.ConverterApp._add_notifications(stub, [{"key": "k", "title": "T", "message": "M"}])
    assert stub.badge == 2
    assert sum("not saved" in r.getMessage() for r in caplog.records) == 2


# ------------------------------------------------------------------ the price refresh
class _Setup:
    """The real refresh worker with only the data sources replaced."""

    def __init__(self, monkeypatch, store):
        import exporters.biglietti_exporter as bx
        import utility.source_manager as sm
        import gui.tabs.situazione_refresh as rf
        self.bx, self.rf, self.store = bx, rf, store
        self.frame = pd.DataFrame([{"partita": "P1", "colore": "C1", "articolo": "A", "codice": "1", "mc": "24",
                                    "prezzo": "4.00", "comment": "", "ordine": "O-1", "riga": 1}])
        monkeypatch.setattr(sm, "load", lambda name: {"wincoint": self.frame, "dfm": self.frame,
                                                       "listini": pd.DataFrame([{"x": 1}])}[name])
        monkeypatch.setattr(rf.business_logic, "compute_situation", lambda orders_df, dfm_df: self.frame)
        monkeypatch.setattr(rf, "post_to_ui", lambda widget, callback, *args: callback(*args))
        self.lookup_calls = 0
        self.good = {("A", "1"): (1, 5.0)}                   # expected 5.00 + 2.00 machine surcharge = 7.00
        monkeypatch.setattr(bx, "load_prezzo_lookup", self._lookup)
        self.lookup_behaviour = lambda call_number: (self.good, "SQLite")

    def _lookup(self):
        self.lookup_calls += 1
        return self.lookup_behaviour(self.lookup_calls)

    def run(self):
        done, result = threading.Event(), []
        widget = type("W", (self.rf.SituationRefreshMixin,), {})()
        self.rf.SituationRefreshMixin.refresh_price_notifications_from_db(
            widget, lambda error: (result.append(error), done.set()))
        assert done.wait(10)
        return result[0]


@pytest.fixture
def refresh(store, monkeypatch):
    return _Setup(monkeypatch, store)


def _open_keys(store):
    return sorted(n["key"] for n in store.list_open())


def test_the_listini_lookup_is_loaded_once_so_a_second_failure_cannot_save_false_alerts(refresh, store):
    # Before: the 2nd load (inside the recompute) failed silently, the refresh reported success, the correct
    # alert was closed and a false "Prezzo Listini mancante" alert was saved.
    refresh.lookup_behaviour = lambda n: (refresh.good, "SQLite") if n == 1 else (_ for _ in ()).throw(OSError("disk I/O error"))
    store.add("situazione-price-mismatch:A:1:P1 (C1):4.0:7.0", "Color price differs from Prezzi", "m", "Situazione Generale", "high")

    assert refresh.run() is None
    assert refresh.lookup_calls == 1
    assert _open_keys(store) == ["situazione-price-mismatch:A:1:P1 (C1):4.0:7.0"]


def test_a_failed_check_changes_no_notification_and_is_reported_and_logged(refresh, store, caplog):
    store.add("situazione-price-mismatch:keep", "T", "M", "Situazione Generale", "high")
    refresh.lookup_behaviour = lambda n: (_ for _ in ()).throw(OSError("disk I/O error"))

    with caplog.at_level("WARNING", logger="converter"):
        error = refresh.run()

    assert isinstance(error, OSError)
    assert _open_keys(store) == ["situazione-price-mismatch:keep"]            # nothing was closed or added
    assert any(r.exc_info and r.exc_info[0] is OSError for r in caplog.records)  # traceback in converter.log


def test_a_missing_source_is_a_logged_warning_not_a_traceback(refresh, store, caplog, monkeypatch):
    import utility.source_manager as sm
    monkeypatch.setattr(sm, "load", lambda name: None)
    store.add("situazione-price-mismatch:keep", "T", "M", "Situazione Generale", "high")

    with caplog.at_level("WARNING", logger="converter"):
        error = refresh.run()

    assert isinstance(error, refresh.rf.PriceSourcesUnavailable) and isinstance(error, ValueError)
    assert _open_keys(store) == ["situazione-price-mismatch:keep"]
    assert any("not refreshed" in r.getMessage() and not r.exc_info for r in caplog.records)


def test_a_corrupt_store_does_not_stop_the_refresh_and_its_content_is_kept_once(refresh, store, tmp_path, caplog):
    original = json.dumps(_history())
    store._PATH.write_text(original, encoding="utf-8")
    # a corrupt store: the refresh still completes and the old content is kept, once, as a separate file
    store._PATH.write_text(original[:-20], encoding="utf-8")

    assert refresh.run() is None
    assert len(_corrupt_copies(tmp_path)) == 1
    assert "situazione-price-mismatch:A:1:P1 (C1):4.0:7.0" in _open_keys(store)
