"""Background source uploads (Situazione) and the refresh that follows them.

The tab is replaced by a small host class, worker threads run inline and Tk's after()
queues callbacks the way the event loop would (an exception in one is reported there and
never reaches the code that scheduled it), so what runs is the real upload logic.
"""
import types

import pandas as pd
import pytest

from utility import situazione_db as db

pytest.importorskip("tkinter")

from gui.tabs import situazione_refresh, situazione_sources  # noqa: E402
from gui.tabs.situazione_refresh import SituationRefreshMixin  # noqa: E402
from gui.tabs.situazione_sources import SOURCE_ORDER, SituationSourcesMixin  # noqa: E402


class _Button:
    def __init__(self):
        self.state = "normal"

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)


class _Row:
    def __init__(self):
        self.button = _Button()
        self.status = None

    def set_status(self, ok, text):
        self.status = (ok, text)

    def winfo_exists(self):
        return True


class Host(SituationSourcesMixin, SituationRefreshMixin):
    def __init__(self):
        self.loaded_frames = {}
        self.source_rows = {key: _Row() for key in SOURCE_ORDER}
        self.codes_row, self.listini_row = _Row(), _Row()
        self._copertura_revision = 0
        self.pending = []
        self.callback_errors = []
        self.shared_changes = 0
        self._on_shared_cache_changed = self._record_shared_change
        self.summary_lbl = types.SimpleNamespace(config=lambda **k: None)
        self.table_loads = 0
        self.prezzo_refreshes = 0

    def _record_shared_change(self):
        self.shared_changes += 1

    def after(self, _ms, callback=None, *args):
        if callback:
            self.pending.append((callback, args))

    def drain(self):
        while self.pending:
            callback, args = self.pending.pop(0)
            try:
                callback(*args)
            except Exception as exc:  # noqa: BLE001 -- what Tk's report_callback_exception would swallow
                self.callback_errors.append(exc)

    def _load_table_from_db(self):
        self.table_loads += 1

    def refresh_prezzo_densita(self):
        self.prezzo_refreshes += 1


@pytest.fixture
def env(tmp_path, monkeypatch):
    class InlineThread:
        def __init__(self, target=None, args=(), kwargs=None, daemon=None, name=None):
            self._target, self._args, self._kwargs = target, args, kwargs or {}

        def start(self):
            self._target(*self._args, **self._kwargs)

    inline = types.SimpleNamespace(Thread=InlineThread)
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "t.sqlite3"))
    db.init_db()
    monkeypatch.setattr(situazione_sources, "threading", inline)
    monkeypatch.setattr(situazione_refresh, "threading", inline)
    registered = []
    monkeypatch.setattr(situazione_sources, "save_source", lambda key, path: registered.append((key, str(path))))
    warnings = []
    monkeypatch.setattr(situazione_sources.messagebox, "showwarning", lambda *a, **k: warnings.append(a))
    return types.SimpleNamespace(tmp=tmp_path, registered=registered, warnings=warnings, monkeypatch=monkeypatch)


def _frame(n=3, price=1.0):
    return pd.DataFrame({"partita": [str(157890 + i) for i in range(n)], "mc": [price] * n,
                         "data_uscita": pd.to_datetime(["2026-10-03"] * n)})


def _loader(frame=None, errors=()):
    return ("Label", lambda path: (frame, list(errors)))


# ---------------------------------------------------------------- one source

def test_a_successful_upload_is_saved_in_sqlite_and_published(env):
    host = Host()
    env.monkeypatch.setitem(situazione_sources.data_loaders.LOADERS, "uscita", _loader(_frame()))
    refreshes = []
    host._refresh_after_upload_async = lambda: refreshes.append(1)

    host._queue_handle_upload("uscita", str(env.tmp / "uscita.xlsx"))
    assert host.source_rows["uscita"].button.state == "disabled"          # while it imports
    host.drain()

    assert host.callback_errors == []
    assert len(host.loaded_frames["uscita"]) == 3
    assert host.source_rows["uscita"].status == (True, "✅ 3 rows")
    assert host.source_rows["uscita"].button.state == "normal"
    assert str(db.load_frame_cache("uscita")["data_uscita"].dtype).startswith("datetime64")
    assert db.get_all_uploads()["uscita"]["status"] == "ok"
    assert env.registered == [("uscita", str(env.tmp / "uscita.xlsx"))]
    assert refreshes == [1] and host.shared_changes == 1
    assert host._source_uploading == set()


def test_a_failed_upload_keeps_the_previous_data_and_reports_why(env):
    host = Host()
    old = _frame(2)
    host.loaded_frames["uscita"] = old
    env.monkeypatch.setitem(situazione_sources.data_loaders.LOADERS, "uscita",
                            _loader(None, ["Missing column Data Uscita"]))

    host._queue_handle_upload("uscita", str(env.tmp / "bad.xlsx"))
    host.drain()

    assert host.loaded_frames["uscita"] is old
    ok, text = host.source_rows["uscita"].status
    assert ok is False and "Missing column Data Uscita" in text
    assert host.source_rows["uscita"].button.state == "normal"
    assert db.get_all_uploads()["uscita"]["status"] == "error"
    assert host.shared_changes == 0


def test_uploading_the_same_source_twice_at_once_is_ignored(env):
    host = Host()
    started = []
    env.monkeypatch.setitem(situazione_sources.data_loaders.LOADERS, "uscita",
                            ("L", lambda path: (started.append(path), (_frame(), []))[1]))
    host._refresh_after_upload_async = lambda: None

    host._queue_handle_upload("uscita", "a.xlsx")
    host._queue_handle_upload("uscita", "b.xlsx")           # the first one has not been published yet
    host.drain()

    assert started == ["a.xlsx"]


def test_the_button_comes_back_even_when_publishing_the_result_fails(env):
    host = Host()
    env.monkeypatch.setitem(situazione_sources.data_loaders.LOADERS, "uscita", _loader(_frame()))

    def explode():
        raise RuntimeError("table failed to refresh")

    host._refresh_after_upload_async = explode
    host._queue_handle_upload("uscita", str(env.tmp / "uscita.xlsx"))
    host.drain()

    assert len(host.callback_errors) == 1
    assert host.source_rows["uscita"].button.state == "normal"       # not disabled for the rest of the session
    assert host._source_uploading == set()
    host._queue_handle_upload("uscita", str(env.tmp / "uscita.xlsx"))   # and it can be used again
    assert host.source_rows["uscita"].button.state == "disabled"


def test_dfm_and_produzione_uploads_also_update_their_shared_reference(env):
    host = Host()
    calls = []
    host._save_shared_dfm = lambda path: calls.append(("dfm", path))
    host._save_shared_prod = lambda path: calls.append(("prod", path))
    host._refresh_after_upload_async = lambda: None
    for key in ("dfm", "data_prod"):
        env.monkeypatch.setitem(situazione_sources.data_loaders.LOADERS, key, _loader(_frame()))

    host._queue_handle_upload("dfm", "DFM.xlsx")
    host._queue_handle_upload("data_prod", "Prod.xlsx")
    host.drain()

    assert calls == [("dfm", "DFM.xlsx"), ("prod", "Prod.xlsx")]


# ---------------------------------------------------------------- Articoli and Listini

def test_articoli_upload_saves_codes_and_says_so_when_nothing_changed(env):
    host = Host()
    codes = pd.DataFrame({"articolo_filato": ["G010003S"], "titolo": ["NE 30/1"]})
    env.monkeypatch.setattr(situazione_sources.data_loaders, "load_codes", lambda path: (codes, []))

    host._queue_codes_upload("codes", str(env.tmp / "Articoli.xlsx"))
    host.drain()
    assert env.warnings == []                                    # first time: new data
    assert host.codes_row.status[0] is True and host.codes_row.button.state == "normal"
    assert db.load_frame_cache("codes") is not None

    host._queue_codes_upload("codes", str(env.tmp / "Articoli.xlsx"))
    host.drain()
    assert len(env.warnings) == 1 and "identical" in env.warnings[0][1]    # same file again
    assert host.callback_errors == []


def test_listini_upload_saves_the_snapshot_and_refreshes_prices(env):
    host = Host()
    listini = pd.DataFrame([{"CLARTICOLO": "C010003S", "CLCOLORE": "00101", "PREZZOLPZ": 4.0, "LIVELLOLPZ": 1}])
    import calculate.prezzi as prezzi_logic
    import utility.prezzi_cache as prezzi_cache

    env.monkeypatch.setattr(prezzi_logic, "load_prezzi", lambda path: (listini, []))
    env.monkeypatch.setattr(prezzi_cache, "save_prezzi_cache", lambda path: None)

    host._queue_listini_upload("listini", str(env.tmp / "Listini.xlsx"))
    host.drain()

    assert host.listini_row.status == (True, "✅ 1 rows")
    assert db.load_frame_cache("listini").loc[0, "PREZZOLPZ"] == 4.0
    assert host.prezzo_refreshes == 1 and host.shared_changes == 1


def test_a_listini_that_cannot_be_read_leaves_the_button_usable(env):
    host = Host()
    import calculate.prezzi as prezzi_logic

    env.monkeypatch.setattr(prezzi_logic, "load_prezzi", lambda path: (None, ["not a Listini file"]))

    host._queue_listini_upload("listini", str(env.tmp / "x.xlsx"))
    host.drain()

    assert host.listini_row.status[0] is False and host.listini_row.button.state == "normal"
    assert db.load_frame_cache("listini") is None


# ---------------------------------------------------------------- the refresh that follows an upload

def _all_sources(host):
    from tests.test_runtime_fixes import _situazione_frames
    host.loaded_frames.update(_situazione_frames())


def test_refresh_after_upload_waits_until_every_source_is_loaded(env):
    host = Host()
    host.loaded_frames["wincoint"] = pd.DataFrame({"partita": ["1"]})

    host._refresh_after_upload_async()
    host.drain()

    assert host.table_loads == 0 and getattr(host, "_background_refresh_running", False) is False


def test_refresh_after_upload_recomputes_and_stores_the_situation(env):
    host = Host()
    _all_sources(host)

    host._refresh_after_upload_async()
    host.drain()

    assert host.callback_errors == []
    assert host.table_loads == 1
    states = db.get_all_states()
    assert set(states) == {"157890", "157891", "157892"}
    assert host._background_refresh_running is False


def test_uploads_arriving_during_a_refresh_are_coalesced_into_one_more_pass(env):
    host = Host()
    _all_sources(host)

    host._refresh_after_upload_async()                 # refresh #1 is now in flight (result not published yet)
    host._refresh_after_upload_async()                 # two more uploads land meanwhile ...
    host._refresh_after_upload_async()
    assert host._background_refresh_pending is True
    host.drain()                                       # #1 publishes, then exactly one follow-up pass runs

    assert host.callback_errors == []
    assert host.table_loads == 2                       # not 3: the two requests became one
    assert host._background_refresh_running is False and host._background_refresh_pending is False


def test_a_failing_refresh_is_logged_and_does_not_block_the_next_one(env):
    host = Host()
    _all_sources(host)
    env.monkeypatch.setattr(situazione_refresh.business_logic, "compute_situation",
                            lambda **kwargs: (_ for _ in ()).throw(ValueError("bad data")))

    host._refresh_after_upload_async()
    host.drain()

    assert host.table_loads == 0 and host._background_refresh_running is False
    env.monkeypatch.undo()
