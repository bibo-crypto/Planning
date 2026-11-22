"""utility/warmup.py: background imports that only change WHEN heavy modules are imported, and never fail the program."""
import sys

import pytest

from utility import warmup


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(warmup, "_started", [])
    monkeypatch.delenv("PLANNING_NO_WARMUP", raising=False)


def test_each_chain_runs_on_its_own_daemon_thread_and_imports_its_modules_in_order(monkeypatch):
    imported = []
    monkeypatch.setattr(warmup.importlib, "import_module", lambda name: imported.append(name))
    threads = warmup.start_import_warmup((("a1", "a2"), ("b1",)))
    for thread in threads:
        thread.join(5)
    assert len(threads) == 2 and all(t.daemon for t in threads)
    assert imported.index("a1") < imported.index("a2") and sorted(imported) == ["a1", "a2", "b1"]


def test_it_starts_only_once(monkeypatch):
    monkeypatch.setattr(warmup.importlib, "import_module", lambda name: None)
    first = warmup.start_import_warmup((("x",),))
    for thread in first:
        thread.join(5)
    assert len(first) == 1
    assert warmup.start_import_warmup((("x",),)) == []


def test_the_environment_variable_switches_it_off(monkeypatch):
    monkeypatch.setenv("PLANNING_NO_WARMUP", "1")
    assert warmup.start_import_warmup((("x",),)) == []


def test_a_module_that_cannot_be_imported_is_swallowed_and_stops_only_its_own_chain(monkeypatch):
    imported = []

    def fake_import(name):
        imported.append(name)
        if name == "broken":
            raise ImportError("no such module")

    monkeypatch.setattr(warmup.importlib, "import_module", fake_import)
    threads = warmup.start_import_warmup((("broken", "never_reached"), ("fine",)))
    for thread in threads:
        thread.join(5)
    assert "never_reached" not in imported and "fine" in imported       # the other chain is unaffected, nothing was raised


def test_the_real_chains_leave_the_modules_importable_and_identical_to_a_normal_import():
    threads = warmup.start_import_warmup()
    for thread in threads:
        thread.join(60)
    import openpyxl
    import pandas
    assert sys.modules["pandas"] is pandas and sys.modules["openpyxl"] is openpyxl
    assert pandas.DataFrame({"a": [1]}).shape == (1, 1)
