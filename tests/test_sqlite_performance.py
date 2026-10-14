"""Regression coverage for the SQLite upload/read performance hardening."""
import pandas as pd

from utility import situazione_db, source_manager


def test_source_manager_decodes_snapshot_once_per_fingerprint(monkeypatch, tmp_path):
    db_path = tmp_path / "source.sqlite3"
    monkeypatch.setattr(situazione_db, "DB_PATH", str(db_path))
    monkeypatch.setattr(source_manager, "_MEMORY", {})
    situazione_db.init_db()
    frame = pd.DataFrame({"article": ["C010027S", "C010028S"], "color": ["1040", "0012"]})
    source_manager.save("dfm_test", frame)

    calls = {"count": 0}
    original = situazione_db.load_frame_cache

    def counted(name):
        calls["count"] += 1
        return original(name)

    monkeypatch.setattr(situazione_db, "load_frame_cache", counted)
    first = source_manager.load("dfm_test")
    second = source_manager.load("dfm_test")
    assert calls["count"] == 0  # save populated the process-local cache
    assert first.to_dict("records") == second.to_dict("records")
    first.loc[0, "article"] = "MUTATED"
    assert source_manager.load("dfm_test").loc[0, "article"] == "C010027S"


def test_snapshot_payload_round_trip_preserves_leading_zero_strings(monkeypatch, tmp_path):
    db_path = tmp_path / "source.sqlite3"
    monkeypatch.setattr(situazione_db, "DB_PATH", str(db_path))
    situazione_db.init_db()
    frame = pd.DataFrame({"article": ["C010027S"], "color": ["001040"], "level": [39]})
    assert situazione_db.save_frame_cache("leading_zeros", frame) is True
    loaded = situazione_db.load_frame_cache("leading_zeros")
    assert loaded.loc[0, "color"] == "001040"
    assert int(loaded.loc[0, "level"]) == 39
    assert situazione_db.save_frame_cache("leading_zeros", frame.copy()) is False
