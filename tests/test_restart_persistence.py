"""Restart / persistence: what one program run saves, the NEXT run (a separate process) must find.

Every step is a fresh ``python`` process pointed at the same throw-away data folder, so connections,
module-level state and caches cannot leak between runs the way they would if the same functions were called
twice in one process.  Nothing here touches a real database.
"""
import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def run(data_dir: Path, code: str) -> dict:
    """Run *code* in a new process; it must print one JSON object on its last line."""
    env = dict(os.environ, PLANNING_DATA_DIR=str(data_dir), PYTHONPATH=str(ROOT))
    done = subprocess.run(
        [sys.executable, "-c", textwrap.dedent(code)], cwd=ROOT, env=env,
        capture_output=True, text=True, timeout=120,
    )
    assert done.returncode == 0, done.stderr
    return json.loads(done.stdout.strip().splitlines()[-1])


SAVE = """
    import json, pandas as pd
    from utility import situazione_db as db
    db.init_db()
    frame = pd.DataFrame({"codice": ["00123", "00456"], "qta": [1.5, 2.0], "note": ["a", None]})
    changed = db.save_frame_cache("dfm", frame, source_path=r"@SRC@")
    db.save_upload("dfm", "dfm.xlsx", 2, "ok", "imported", file_path=r"@SRC@")
    db.upsert_states([{"partita": "P1", "new_comment": "first"}, {"partita": "P2", "new_comment": "second"}])
    db.save_codes(pd.DataFrame({"articolo_filato": ["A1"], "titolo": ["30/1"]}))
    print(json.dumps({"changed": bool(changed)}))
"""

LOAD = """
    import json
    from utility import situazione_db as db
    db.init_db()
    frame = db.load_frame_cache("dfm")
    states = db.get_all_states()
    print(json.dumps({
        "rows": frame.to_dict("records"), "dtypes": {c: str(t) for c, t in frame.dtypes.items()},
        "fingerprint": db.snapshot_fingerprint("dfm"), "meta": db.snapshot_meta("dfm"),
        "upload": db.get_upload("dfm"), "states": {k: v["new_comment"] for k, v in states.items()},
        "codes": db.load_codes(),
    }, default=str))
"""


@pytest.fixture()
def source_file(tmp_path):
    path = tmp_path / "dfm.xlsx"
    path.write_bytes(b"x")
    return path


def test_everything_saved_by_one_run_is_there_in_the_next_run(tmp_path, source_file):
    data = tmp_path / "appdata"
    assert run(data, SAVE.replace("@SRC@", str(source_file)))["changed"] is True
    loaded = run(data, LOAD)
    first, second = loaded["rows"]
    assert first == {"codice": "00123", "qta": 1.5, "note": "a"}
    assert (second["codice"], second["qta"]) == ("00456", 2.0)
    assert second["note"] != second["note"]                             # an empty cell comes back empty (NaN), not as text
    assert loaded["rows"][0]["codice"] == "00123"                       # a code is not turned into a number
    assert loaded["upload"]["row_count"] == 2 and loaded["upload"]["file_path"] == str(source_file)
    assert loaded["states"] == {"P1": "first", "P2": "second"}
    assert loaded["codes"] == {"A1": "30/1"}
    assert loaded["meta"]["source_path"] == str(source_file)


def test_restarting_many_times_adds_no_duplicates_and_keeps_the_fingerprint(tmp_path, source_file):
    data = tmp_path / "appdata"
    run(data, SAVE.replace("@SRC@", str(source_file)))
    first = run(data, LOAD)
    for _ in range(3):                                                  # three more starts, init_db each time
        again = run(data, LOAD)
        assert again["fingerprint"] == first["fingerprint"] and again["rows"] == first["rows"]
        assert again["states"] == first["states"]


def test_saving_identical_data_again_in_a_new_run_reports_no_change(tmp_path, source_file):
    data = tmp_path / "appdata"
    assert run(data, SAVE.replace("@SRC@", str(source_file)))["changed"] is True
    assert run(data, SAVE.replace("@SRC@", str(source_file)))["changed"] is False  # same content: nothing is rewritten
    assert len(run(data, LOAD)["states"]) == 2                          # and the states were not doubled


def test_a_run_leaves_no_open_transaction_or_lock_behind(tmp_path, source_file):
    data = tmp_path / "appdata"
    run(data, SAVE.replace("@SRC@", str(source_file)))
    db_file = data / "situazione" / "dyeing_tracker.db"
    import sqlite3
    conn = sqlite3.connect(db_file, timeout=0.2)                        # fails fast if a writer is still holding it
    try:
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("ROLLBACK")
        assert conn.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    finally:
        conn.close()


def test_a_changed_source_file_is_noticed_through_the_stored_file_time(tmp_path, source_file):
    data = tmp_path / "appdata"
    run(data, SAVE.replace("@SRC@", str(source_file)))
    stored = run(data, LOAD)["meta"]["source_mtime_ns"]
    assert stored == source_file.stat().st_mtime_ns                     # what the next start compares with
    os.utime(source_file, ns=(stored + 5_000_000_000, stored + 5_000_000_000))
    assert source_file.stat().st_mtime_ns != run(data, LOAD)["meta"]["source_mtime_ns"]
