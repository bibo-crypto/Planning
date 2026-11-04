"""Regression tests for the Phase 2 reliability fixes.

* every Situazione DB function closes its SQLite connection even when a statement fails;
* the on-disk cache is keyed by the application version, so a new release never serves a
  pickle that an older loader wrote;
* no module swallows ``except Exception`` without leaving a trace in the log.
"""
import ast
import pathlib
import sqlite3

import pandas as pd
import pytest

from utility import disk_cache, situazione_db

ROOT = pathlib.Path(__file__).resolve().parents[1]


class _FailingConnection:
    """Stands in for a sqlite3 connection whose every statement fails."""

    def __init__(self):
        self.closed = False
        self.row_factory = None

    def execute(self, *args, **kwargs):
        raise sqlite3.OperationalError("boom")

    executemany = executescript = execute

    def commit(self):
        pass

    def rollback(self):
        pass

    def close(self):
        self.closed = True


_CALLS = {
    "init_db": lambda: situazione_db.init_db(),
    "save_upload": lambda: situazione_db.save_upload("src", "f.xlsx", 1, "ok", "m"),
    "get_upload": lambda: situazione_db.get_upload("src"),
    "get_all_uploads": lambda: situazione_db.get_all_uploads(),
    "save_codes": lambda: situazione_db.save_codes(pd.DataFrame({"articolo_filato": ["a"], "titolo": ["t"]})),
    "load_codes": lambda: situazione_db.load_codes(),
    "get_all_states": lambda: situazione_db.get_all_states(),
    "upsert_states": lambda: situazione_db.upsert_states([{"partita": "P1"}]),
    "remove_states_not_in": lambda: situazione_db.remove_states_not_in(["P1"]),
}


@pytest.mark.parametrize("name", sorted(_CALLS))
def test_situazione_db_closes_its_connection_when_a_statement_fails(name, monkeypatch):
    connection = _FailingConnection()
    monkeypatch.setattr(situazione_db, "get_conn", lambda: connection)
    with pytest.raises(sqlite3.OperationalError):
        _CALLS[name]()
    assert connection.closed, f"{name} left its SQLite connection open after an error"


def test_situazione_db_still_round_trips_data(tmp_path, monkeypatch):
    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "t.db"))
    situazione_db.init_db()
    situazione_db.save_upload("wincoint", "w.xlsx", 3, "ok", "fine")
    assert situazione_db.get_upload("wincoint")["row_count"] == 3
    assert set(situazione_db.get_all_uploads()) == {"wincoint"}
    situazione_db.save_codes(pd.DataFrame({"articolo_filato": ["C1"], "titolo": ["24/1"]}))
    assert situazione_db.load_codes() == {"C1": "24/1"}
    assert situazione_db.upsert_states([{"partita": "P1", "new_comment": "a"}, {"partita": " "}]) == (1, 0, 0)
    assert situazione_db.upsert_states([{"partita": "P1", "new_comment": "b"}]) == (0, 1, 0)
    assert situazione_db.upsert_states([{"partita": "P1", "new_comment": "b"}]) == (0, 0, 1)
    assert set(situazione_db.get_all_states()) == {"P1"}
    assert situazione_db.remove_states_not_in(["P2"]) == 1
    assert situazione_db.get_all_states() == {}


def test_cache_file_name_depends_on_the_code_version(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_cache, "_cache_dir", lambda: tmp_path)
    key = ("source.xlsx", 1, 2)
    monkeypatch.setattr(disk_cache, "_code_version", lambda: "1.0")
    old = disk_cache._cache_path("ns", key)
    monkeypatch.setattr(disk_cache, "_code_version", lambda: "2.0")
    assert disk_cache._cache_path("ns", key) != old


def test_a_pickle_written_by_an_older_version_is_not_served(monkeypatch, tmp_path):
    monkeypatch.setattr(disk_cache, "_cache_dir", lambda: tmp_path)
    source = tmp_path / "source.xlsx"
    source.write_text("x")
    disk_cache._MEMORY_CACHE.clear()
    monkeypatch.setattr(disk_cache, "_code_version", lambda: "1.0")
    assert disk_cache.cached_load("ns", source, lambda: "from old loader") == "from old loader"
    disk_cache._MEMORY_CACHE.clear()
    assert disk_cache.cached_load("ns", source, lambda: "unused") == "from old loader"   # same version: disk hit
    disk_cache._MEMORY_CACHE.clear()
    monkeypatch.setattr(disk_cache, "_code_version", lambda: "2.0")
    assert disk_cache.cached_load("ns", source, lambda: "from new loader") == "from new loader"
    disk_cache._MEMORY_CACHE.clear()


def _source_files():
    for directory in ("calculate", "exporters", "gui", "parsers", "pipelines", "utility"):
        yield from (ROOT / directory).rglob("*.py")
    # main.py is deliberately left out: its last-resort startup handler must not import
    # utility.utils (and so set up logging) before it has protected itself.
    for name in ("publish.py", "runtime_hook.py", "sync_venv_packages.py"):
        if (ROOT / name).exists():
            yield ROOT / name


def test_no_broad_except_swallows_errors_without_a_trace():
    offenders = []
    for path in _source_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            broad = node.type is None or (isinstance(node.type, ast.Name) and node.type.id in {"Exception", "BaseException"})
            if broad and all(isinstance(statement, ast.Pass) for statement in node.body):
                offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
    assert not offenders, "except Exception: pass with no logging at " + ", ".join(offenders)
