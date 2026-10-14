"""Compatibility and type-preservation tests for the compact SQLite snapshot format."""
import json

import pandas as pd

from utility import situazione_db as db


def test_compact_payload_round_trip_preserves_zero_padded_codes_and_dates(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "source.sqlite3"))
    db.init_db()
    frame = pd.DataFrame({
        "article": pd.Series(["C010027S", "C010028S"], dtype="object"),
        "color": pd.Series(["001040", "000007"], dtype="object"),
        "event_date": pd.to_datetime(["2026-09-01", None]),
        "quantity": pd.Series([32, 40], dtype="int64"),
    })

    assert db.save_frame_cache("payload", frame) is True
    restored = db.load_frame_cache("payload")
    assert restored["color"].tolist() == ["001040", "000007"]
    assert str(restored["event_date"].dtype).startswith("datetime64")
    assert restored["quantity"].tolist() == [32, 40]

    conn = db.get_conn()
    row = conn.execute("SELECT payload_json, column_meta, schema_version FROM source_snapshot WHERE source_name='payload'").fetchone()
    conn.close()
    assert row["payload_json"] and row["column_meta"] and row["schema_version"] == 3
    assert db.save_frame_cache("payload", frame.copy()) is False


def test_legacy_row_snapshots_are_migrated_to_compact_payload_on_first_read(monkeypatch, tmp_path):
    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "legacy.sqlite3"))
    db.init_db()
    frame = pd.DataFrame({"partita": ["1", "2"], "data_uscita": pd.to_datetime(["2026-10-01", None])})
    meta = db._column_meta(frame)
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO source_snapshot(source_name,schema_version,source_path,source_mtime_ns,row_count,saved_at,data_fingerprint,column_meta,payload_json) "
        "VALUES(?,?,?,?,?,?,?,?,NULL)",
        ("legacy", 2, None, None, len(frame), "2026-10-10", db.frame_fingerprint(frame), meta),
    )
    conn.executemany(
        "INSERT INTO source_snapshot_row(source_name,row_number,row_json) VALUES(?,?,?)",
        [("legacy", 0, json.dumps({"partita": "1", "data_uscita": "2026-10-01 00:00:00"})),
         ("legacy", 1, json.dumps({"partita": "2", "data_uscita": "NaT"}))],
    )
    conn.commit()
    conn.close()

    loaded = db.load_frame_cache("legacy")
    assert str(loaded["data_uscita"].dtype).startswith("datetime64")
    conn = db.get_conn()
    row = conn.execute("SELECT payload_json, column_meta, schema_version FROM source_snapshot WHERE source_name='legacy'").fetchone()
    remaining = conn.execute("SELECT COUNT(*) FROM source_snapshot_row WHERE source_name='legacy'").fetchone()[0]
    conn.close()
    assert row["payload_json"] and row["column_meta"] and row["schema_version"] == 3
    assert remaining == 0


def _legacy_epoch_json(frame) -> str:
    # The old cache format stored datetimes as epoch milliseconds, which is
    # exactly what this test must reproduce -- pandas now warns about it.
    import warnings
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return frame.to_json(orient="records", force_ascii=False)


def test_source_manager_migrates_legacy_frame_cache_and_caches_it_in_memory(monkeypatch, tmp_path):
    from utility import source_manager

    monkeypatch.setattr(db, "DB_PATH", str(tmp_path / "legacy_frame_cache.sqlite3"))
    monkeypatch.setattr(source_manager, "_MEMORY", {})
    db.init_db()
    frame = pd.DataFrame({"article": ["C010027S"], "color": ["001040"],
                          "data": pd.to_datetime(["2026-10-01"])})
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO frame_cache(source_name,data_json,saved_at) VALUES(?,?,?)",
        ("legacy_source", _legacy_epoch_json(frame), "2026-10-10"),
    )
    conn.commit()
    conn.close()

    restored = source_manager.load("legacy_source")
    assert restored["article"].tolist() == frame["article"].tolist()
    assert restored["color"].tolist() == frame["color"].tolist()
    assert str(restored["data"].dtype).startswith("datetime64")
    conn = db.get_conn()
    snapshot = conn.execute(
        "SELECT payload_json, data_fingerprint FROM source_snapshot WHERE source_name='legacy_source'"
    ).fetchone()
    legacy_count = conn.execute(
        "SELECT COUNT(*) FROM frame_cache WHERE source_name='legacy_source'"
    ).fetchone()[0]
    conn.close()
    assert snapshot["payload_json"] and snapshot["data_fingerprint"]
    assert legacy_count == 0

    # Once restored, repeated consumers use the process cache and do not decode the DB again.
    monkeypatch.setattr(db, "load_frame_cache", lambda _name: (_ for _ in ()).throw(AssertionError("unexpected reload")))
    assert source_manager.load("legacy_source").to_dict("records") == frame.to_dict("records")


def test_sqlite_snapshot_helpers_are_not_accidentally_redefined():
    import ast
    from pathlib import Path

    module = Path(db.__file__)
    tree = ast.parse(module.read_text(encoding="utf-8"))
    names = [node.name for node in tree.body if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    for helper in ("frame_fingerprint", "save_frame_cache", "_restore_frame", "load_frame_cache"):
        assert names.count(helper) == 1, f"{helper} has {names.count(helper)} top-level definitions"
