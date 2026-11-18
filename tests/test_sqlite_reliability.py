"""SQLite reliability with real files and real processes.

* databases exactly as eight older releases left them (rebuilt from each release's own init_db, stored in
  tests/fixtures/legacy_database_schemas.json) are upgraded without losing a row;
* a program killed in the middle of saving leaves a database that opens, passes integrity_check and holds one COMPLETE
  snapshot (never a mix of two);
* several processes writing and reading at the same time neither fail with "database is locked" nor lose a write;
* a backup taken while the data still lives in the -wal file contains that data, and restoring it brings it back;
* a backup that holds a damaged database is refused before anything is replaced.
"""
import json
import os
import sqlite3
import subprocess
import sys
import time
import zipfile
from pathlib import Path

import pandas as pd
import pytest

from utility import backup, orders_db, prezzi_db, situazione_db

ROOT = Path(__file__).resolve().parent.parent
LEGACY = json.loads((ROOT / "tests" / "fixtures" / "legacy_database_schemas.json").read_text(encoding="utf-8"))


def integrity(path):
    conn = sqlite3.connect(path)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def columns_of(conn, table):
    return [row[1] for row in conn.execute(f"PRAGMA table_info({table})")]


def sample_row(conn, table):
    """One row for *table* with a value for every column, by the column's type."""
    values = {}
    info = list(conn.execute(f"PRAGMA table_info({table})"))
    rowid_alias = [c for c in info if c[5]] if sum(1 for c in info if c[5]) == 1 else []      # a lone INTEGER PRIMARY KEY fills itself
    for _cid, name, ctype, notnull, default, pk in info:
        if rowid_alias and pk and "INT" in (ctype or "").upper():
            continue
        kind = (ctype or "TEXT").upper()
        values[name] = 7 if "INT" in kind else 1.5 if ("REAL" in kind or "FLOA" in kind) else b"x" if "BLOB" in kind else f"{table}.{name}"
    names = ", ".join(values)
    conn.execute(f"INSERT INTO {table} ({names}) VALUES ({', '.join('?' * len(values))})", list(values.values()))


def replay(path, statements):
    conn = sqlite3.connect(path)
    try:
        for statement in statements:
            conn.execute(statement)
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
        for table in tables:
            sample_row(conn, table)
        conn.commit()
        return {t: (columns_of(conn, t), conn.execute(f"SELECT * FROM {t} ORDER BY rowid").fetchall()) for t in tables}
    finally:
        conn.close()


# ------------------------------------------------------------------ databases left by older releases
@pytest.mark.parametrize("variant", LEGACY["situazione"], ids=lambda v: f"{v['date']}-{v['commit']}")
def test_the_situazione_database_of_every_older_release_is_upgraded_without_losing_a_row(variant, tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    before = replay(path, variant["statements"])
    monkeypatch.setattr(situazione_db, "DB_PATH", str(path))

    situazione_db.init_db()
    situazione_db.init_db()                                                # a second start changes nothing more

    conn = sqlite3.connect(path)
    try:
        for table, (old_columns, old_rows) in before.items():
            now = conn.execute(f"SELECT {', '.join(old_columns)} FROM {table} ORDER BY rowid").fetchall()
            assert now == old_rows, f"{table}: rows of release {variant['commit']} changed by the upgrade"
        for table, column in situazione_db._LATER_COLUMNS:
            assert column in columns_of(conn, table), f"{table}.{column} missing after the upgrade"
    finally:
        conn.close()
    assert integrity(path) == "ok"
    # the program can read what the old release stored
    assert isinstance(situazione_db.get_all_states(), dict) and isinstance(situazione_db.get_all_uploads(), (dict, list))
    assert isinstance(situazione_db.load_codes(), dict)


def test_the_orders_history_database_of_the_older_release_keeps_its_rows(tmp_path):
    path = tmp_path / "orders_old.db"
    variant = LEGACY["orders"][0]
    conn = sqlite3.connect(path)
    for statement in variant["statements"]:
        conn.execute(statement)
    sample_row(conn, "orders")                                            # every column of the old layout filled
    conn.execute("UPDATE orders SET source_file = ?, sheet_name = 'Orders', partita_col = '77', order_json = ?, status = 'open'",
                 ("old.xlsx", json.dumps({"Partita Col": "77", "Cliente": "Old"})))
    conn.commit()
    conn.close()

    assert [(r["sheet_name"], r["partita_col"]) for r in orders_db.list_open(path)] == [("Orders", "77")]
    orders_db.sync_rows(Path("new.xlsx"), "Orders", [{"Partita Col": "5", "Cliente": "New"}], db_path=path)
    assert sorted(r["partita_col"] for r in orders_db.list_open(path)) == ["5", "77"]
    assert integrity(path) == "ok"


def test_the_listini_cache_database_of_the_older_release_still_works(tmp_path):
    path = tmp_path / "prezzi_old.db"
    conn = sqlite3.connect(path)
    for statement in LEGACY["prezzi"][0]["statements"]:
        conn.execute(statement)
    conn.execute("INSERT INTO prezzi_frame_cache (cache_key, fingerprint, payload) VALUES ('other', 'f', '[]')")
    conn.commit()
    conn.close()
    frame = pd.DataFrame({"codice": ["001", "002"], "prezzo": [4.5, 5.0]})
    prezzi_db.save_prezzi_frame(("fp",), frame, db_path=path)
    loaded = prezzi_db.load_prezzi_frame(("fp",), db_path=path)
    assert loaded is not None and loaded["codice"].tolist() == ["001", "002"]
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT COUNT(*) FROM prezzi_frame_cache WHERE cache_key = 'other'").fetchone()[0] == 1
    conn.close()


# ------------------------------------------------------------------ a program killed while saving
WRITER = """
import sys, pandas as pd
from utility import situazione_db as db
db.init_db()
size, tag, rounds = int(sys.argv[1]), sys.argv[2], int(sys.argv[3])
for i in range(1, rounds + 1):
    frame = pd.DataFrame({"iteration": [i] * size, "codice": [f"{k:06d}" for k in range(size)], "v": [float(k) for k in range(size)]})
    db.save_frame_cache(tag, frame, source_path="x.xlsx")
    db.upsert_states([{"partita": f"{tag}-{k}", "new_comment": str(i)} for k in range(10)])
    print(i, flush=True)
"""


def reap(proc):
    """Wait for a (killed) child and close its pipes."""
    proc.wait(10)
    for stream in (proc.stdout, proc.stderr):
        if stream:
            stream.close()


def child(data_dir, *args, capture=True):
    env = dict(os.environ, PLANNING_DATA_DIR=str(data_dir), PYTHONPATH=str(ROOT))
    return subprocess.Popen([sys.executable, "-c", WRITER, *map(str, args)], cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE)


@pytest.mark.parametrize("delay", [0.0, 0.015, 0.04, 0.08])
def test_a_program_killed_while_saving_leaves_one_complete_snapshot(tmp_path, monkeypatch, delay):
    size = 6000
    proc = child(tmp_path, size, "dfm", 1000)
    seen = 0
    while seen < 3:                                                        # let it save a few snapshots first
        line = proc.stdout.readline()
        assert line, proc.stderr.read()
        seen = int(line)
    time.sleep(delay)
    proc.kill()                                                            # SIGKILL / TerminateProcess: no cleanup runs
    reap(proc)

    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "situazione" / "dyeing_tracker.db"))
    situazione_db.init_db()                                                # reopening replays / discards the -wal
    assert integrity(situazione_db.DB_PATH) == "ok"
    frame = situazione_db.load_frame_cache("dfm")
    assert len(frame) == size and frame["iteration"].nunique() == 1 and int(frame["iteration"].iloc[0]) >= 3
    assert frame["codice"].tolist()[:2] == ["000000", "000001"]


def test_the_program_can_start_and_save_again_after_being_killed(tmp_path, monkeypatch):
    proc = child(tmp_path, 3000, "dfm", 1000)
    assert proc.stdout.readline()
    proc.kill()
    reap(proc)
    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "situazione" / "dyeing_tracker.db"))
    situazione_db.init_db()
    fresh = pd.DataFrame({"iteration": [999] * 5, "codice": list("abcde"), "v": [1.0] * 5})
    situazione_db.save_frame_cache("dfm", fresh, source_path="y.xlsx")
    assert situazione_db.load_frame_cache("dfm")["iteration"].tolist() == [999] * 5


# ------------------------------------------------------------------ several processes at once
def test_processes_writing_and_reading_together_lose_nothing_and_never_hit_a_lock(tmp_path, monkeypatch):
    rounds, writers = 25, 3
    procs = [child(tmp_path, 500, f"src{n}", rounds) for n in range(writers)]
    reader_code = (
        "import sys, time\nfrom utility import situazione_db as db\ndb.init_db()\nend = time.time() + 4\nreads = 0\n"
        "while time.time() < end:\n    db.get_all_states(); db.load_frame_cache('src0'); reads += 1\nprint('reads', reads)\n")
    env = dict(os.environ, PLANNING_DATA_DIR=str(tmp_path), PYTHONPATH=str(ROOT))
    reader = subprocess.Popen([sys.executable, "-c", reader_code], cwd=ROOT, env=env, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    outputs = [p.communicate(timeout=120) for p in procs]
    reader_out, reader_err = reader.communicate(timeout=60)
    for proc, (_out, err) in zip(procs, outputs):
        assert proc.returncode == 0 and "database is locked" not in err, err[-400:]
    assert reader.returncode == 0 and "database is locked" not in reader_err, reader_err[-400:]

    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "situazione" / "dyeing_tracker.db"))
    situazione_db.init_db()
    assert integrity(situazione_db.DB_PATH) == "ok"
    for n in range(writers):
        frame = situazione_db.load_frame_cache(f"src{n}")
        assert len(frame) == 500 and set(frame["iteration"]) == {rounds}              # every writer's last snapshot, complete
    states = situazione_db.get_all_states()
    assert len(states) == writers * 10 and {v["new_comment"] for v in states.values()} == {str(rounds)}   # no write lost


# ------------------------------------------------------------------ backup and restore
@pytest.fixture
def app_data(tmp_path, monkeypatch):
    data = tmp_path / "appdata"
    (data / "situazione").mkdir(parents=True)
    monkeypatch.setattr(backup, "APP_DATA_DIR", data)
    monkeypatch.setattr(situazione_db, "DB_PATH", str(data / "situazione" / "dyeing_tracker.db"))
    (data / "settings.json").write_text('{"theme": "A"}', encoding="utf-8")
    return data


def states(*names, comment="A"):
    return [{"partita": name, "new_comment": comment} for name in names]


def test_a_backup_taken_while_the_data_is_still_in_the_wal_file_contains_it_and_restores_it(app_data, tmp_path):
    situazione_db.init_db()
    holder = sqlite3.connect(situazione_db.DB_PATH)                       # another open reader keeps the data in the -wal file
    holder.execute("BEGIN")
    holder.execute("SELECT COUNT(*) FROM partita_state").fetchall()
    situazione_db.upsert_states(states("P1", "P2", "P3"))
    situazione_db.save_frame_cache("dfm", pd.DataFrame({"a": [1, 2, 3]}), source_path="f.xlsx")
    wal = Path(situazione_db.DB_PATH + "-wal")
    assert wal.exists() and wal.stat().st_size > 0, "the scenario needs the data to live in the -wal file"

    archive = backup.create_backup(tmp_path / "backups" / "planning_backup_test.zip")
    holder.rollback()
    holder.close()

    with zipfile.ZipFile(archive) as z:                                    # the backup holds the WAL-only data (a raw copy would not)
        z.extract("situazione/dyeing_tracker.db", tmp_path / "unzipped")
    copy = sqlite3.connect(tmp_path / "unzipped" / "situazione" / "dyeing_tracker.db")
    assert sorted(r[0] for r in copy.execute("SELECT partita FROM partita_state")) == ["P1", "P2", "P3"]
    copy.close()

    situazione_db.upsert_states(states("P1", comment="CHANGED") + states("P9", comment="B"))      # the data changes afterwards
    (app_data / "settings.json").write_text('{"theme": "B"}', encoding="utf-8")
    assert backup.restore_backup(archive) >= 2

    restored = situazione_db.get_all_states()
    assert sorted(restored) == ["P1", "P2", "P3"] and restored["P1"]["new_comment"] == "A"   # exactly the backed-up state
    assert situazione_db.load_frame_cache("dfm")["a"].tolist() == [1, 2, 3]
    assert integrity(situazione_db.DB_PATH) == "ok"
    assert (app_data / "settings.json").read_text(encoding="utf-8") == '{"theme": "A"}'


def test_a_stale_wal_file_of_the_replaced_database_is_not_replayed_onto_the_restored_one(app_data, tmp_path):
    situazione_db.init_db()
    situazione_db.upsert_states(states("P1"))
    archive = backup.create_backup(tmp_path / "b" / "planning_backup_x.zip")
    situazione_db.upsert_states(states("LATER"))
    stale = Path(situazione_db.DB_PATH + "-wal")
    stale.write_bytes(b"\x00" * 4096)                                      # junk a crashed program could leave behind
    backup.restore_backup(archive)
    assert integrity(situazione_db.DB_PATH) == "ok" and sorted(situazione_db.get_all_states()) == ["P1"]


def test_a_backup_holding_a_damaged_database_is_refused_before_anything_is_replaced(app_data, tmp_path):
    situazione_db.init_db()
    situazione_db.upsert_states(states("GOOD"))
    damaged = tmp_path / "damaged.zip"
    with zipfile.ZipFile(damaged, "w") as z:
        z.writestr("situazione/dyeing_tracker.db", b"this is not a sqlite database" * 100)
        z.writestr("settings.json", '{"theme": "FROM-BACKUP"}')
    before = Path(situazione_db.DB_PATH).read_bytes()
    with pytest.raises(ValueError, match="damaged database"):
        backup.restore_backup(damaged)
    assert Path(situazione_db.DB_PATH).read_bytes() == before                 # the good database was not touched
    assert (app_data / "settings.json").read_text(encoding="utf-8") == '{"theme": "A"}'    # and nothing else was restored
    assert sorted(situazione_db.get_all_states()) == ["GOOD"]


def test_a_file_that_is_not_a_backup_is_refused(app_data, tmp_path):
    not_a_zip = tmp_path / "x.zip"
    not_a_zip.write_text("nope", encoding="utf-8")
    with pytest.raises(ValueError, match="not a valid Planning backup"):
        backup.restore_backup(not_a_zip)
