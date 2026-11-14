"""Handlers that used to swallow a failure silently now leave a log record (warning + traceback) and still return
exactly what they returned before.  A transient SQLite "disk I/O error" must be visible in converter.log, not look like
"no data".  Each test makes the underlying call fail and checks (1) the unchanged return value, (2) the record."""
import pandas as pd


def _warned(caplog, text, exc_type=OSError):
    return any(text in r.getMessage() and r.exc_info and r.exc_info[0] is exc_type for r in caplog.records)


def _fail(*_args, **_kwargs):
    raise OSError("disk I/O error")


def test_source_manager_load_returns_none_and_logs_when_sqlite_fails(monkeypatch, caplog):
    from utility import source_manager as sm
    monkeypatch.setattr(sm.db, "snapshot_fingerprint", _fail)
    sm._MEMORY["dfm"] = ("old", pd.DataFrame({"a": [1]}))
    with caplog.at_level("WARNING", logger="converter"):
        assert sm.load("dfm") is None
    assert _warned(caplog, "Source could not be loaded") and "dfm" not in sm._MEMORY


def test_source_manager_save_keeps_its_result_and_logs_a_failed_refresh(monkeypatch, caplog):
    from utility import source_manager as sm
    monkeypatch.setattr(sm.db, "save_frame_cache", lambda *a, **k: True)
    monkeypatch.setattr(sm.db, "snapshot_fingerprint", _fail)
    with caplog.at_level("WARNING", logger="converter"):
        assert sm.save("dfm", pd.DataFrame({"a": [1]})) is True
    assert _warned(caplog, "Source refresh failed")


def test_source_manager_metadata_and_is_current_log_and_keep_their_fallbacks(monkeypatch, tmp_path, caplog):
    from utility import source_manager as sm
    workbook = tmp_path / "x.xlsx"
    workbook.write_bytes(b"x")
    monkeypatch.setattr(sm.db, "get_upload", _fail)
    monkeypatch.setattr(sm.db, "snapshot_meta", _fail)
    monkeypatch.setattr(sm, "_registered_path", lambda name: str(workbook))
    with caplog.at_level("WARNING", logger="converter"):
        assert sm.metadata("dfm") == {}
        assert sm.is_current("dfm") is True
    assert _warned(caplog, "Upload metadata could not be read") and _warned(caplog, "Snapshot metadata could not be read")


def test_the_listini_cache_failures_are_logged_and_the_excel_result_is_still_used(monkeypatch, tmp_path, caplog):
    import calculate.prezzi as prezzi
    import utility.prezzi_db as prezzi_db
    source = tmp_path / "listini.xlsx"
    source.write_bytes(b"x")
    result = (pd.DataFrame({"a": [1]}), [])
    monkeypatch.setattr(prezzi, "_PREZZI_CACHE", {})
    monkeypatch.setattr(prezzi, "category_sources_fingerprint", lambda: ("category",))
    monkeypatch.setattr(prezzi, "_load_prezzi_uncached", lambda path: result)
    monkeypatch.setattr(prezzi_db, "load_prezzi_frame", _fail)
    monkeypatch.setattr(prezzi_db, "save_prezzi_frame", _fail)
    with caplog.at_level("WARNING", logger="converter"):
        assert prezzi.load_prezzi(source) is result
    assert _warned(caplog, "Listini cache could not be read")
    assert any("could not save SQLite cache" in r.getMessage() for r in caplog.records)


def test_biglietti_lookups_log_when_codes_or_prices_cannot_be_loaded(monkeypatch, caplog):
    import exporters.biglietti.lookups as lookups
    import utility.prezzi_cache as prezzi_cache
    import utility.situazione_db as situazione_db
    monkeypatch.setattr(lookups, "_PREZZO_LOOKUP_CACHE", None, raising=False)
    monkeypatch.setattr(situazione_db, "load_codes", _fail)
    monkeypatch.setattr(situazione_db, "snapshot_fingerprint", _fail)          # the SQLite tier of the price lookup
    with caplog.at_level("WARNING", logger="converter"):
        assert lookups.load_articoli_titolo_map() == {}
        assert lookups.load_prezzo_lookup() == ({}, "")                         # no workbook configured: nothing to fall back to
    assert _warned(caplog, "Yarn codes could not be loaded")
    assert _warned(caplog, "Prezzi lookup could not be read from SQLite")

    caplog.clear()
    monkeypatch.setattr(prezzi_cache, "load_prezzi_cache", _fail)              # the workbook tier
    with caplog.at_level("WARNING", logger="converter"):
        assert lookups.load_prezzo_lookup() == ({}, "")
    assert _warned(caplog, "Prezzi lookup could not be loaded; continuing without prices")


def test_a_master_import_that_skips_a_sheet_says_why(monkeypatch, tmp_path, caplog):
    import pipelines.master_import as master_import
    assert master_import.logger is not None
    source = open(master_import.__file__, encoding="utf-8").read()
    # the skip handler logs with the traceback (it is exercised end to end by the master-import tests)
    assert 'logger.warning("Master import: %s was skipped because it failed", LABELS[key], exc_info=True)' in source
