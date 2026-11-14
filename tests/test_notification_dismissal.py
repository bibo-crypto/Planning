"""Mark Resolved on a problem that is still there: the user decides, and the decision sticks.

Rules under test (utility/notifications.py):
* is_live(): which notification families a completed check keeps up to date.
* dismiss(): resolve by hand although the check still reports it -> it is NOT re-opened by the next check ...
* ... until a completed check stops reporting the key (resolve_missing / resolve), which clears the dismissal,
  so the alert returns if the problem comes back.
* A key whose values changed is a different problem and is reported as new.
"""
import ast
from pathlib import Path

import pytest

PRICE = "situazione-price-mismatch:A:1:P1 (C1):4.0:7.0"
PRICE_CHANGED = "situazione-price-mismatch:A:1:P1 (C1):4.5:7.0"
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def store(tmp_path, monkeypatch):
    from utility import notifications
    monkeypatch.setattr(notifications, "_PATH", tmp_path / "notifications.json")
    return notifications


def _report(store, key, title="Color price differs"):
    return store.add_many([{"key": key, "title": title, "message": "m", "page": "Situazione Generale", "severity": "high"}])


def _open(store):
    return sorted(item["key"] for item in store.list_open())


# ------------------------------------------------------------------ which notifications are "live"
@pytest.mark.parametrize("key, live", [
    (PRICE, True),
    ("situazione-price-missing:A:1:P1", True),
    ("situazione-raw-yarn-available:batch", True),
    ("prezzi-category-missing:X", True),
    ("situazione-abbina-pending", True),
    ("prezzi-price-changes", False),                 # a notice, no check re-reports it
    ("prezzi-price-changes-export", False),
    ("system-backup-restored", False),
    ("planning-situazione-upload-refresh", False),
])
def test_is_live(store, key, live):
    assert store.is_live(key) is live


def test_every_prefix_a_check_resolves_by_is_listed_as_live():
    """A new producer that calls resolve_missing("new-prefix-", ...) must also be added to LIVE_PREFIXES,
    otherwise its problems could be resolved without the warning and re-opened by the next check."""
    from utility import notifications
    prefixes = set()
    for path in list((ROOT / "gui").rglob("*.py")) + list((ROOT / "utility").rglob("*.py")) + list((ROOT / "pipelines").rglob("*.py")):
        if path.name == "notifications.py":
            continue
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        local_names = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
                for target in node.targets:
                    if isinstance(target, ast.Name):
                        local_names[target.id] = node.value.value
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "resolve_missing"
                    and node.args):
                first = node.args[0]
                if isinstance(first, ast.Constant) and isinstance(first.value, str):
                    prefixes.add(first.value)
                elif isinstance(first, ast.Name) and first.id in local_names:
                    prefixes.add(local_names[first.id])
                else:
                    pytest.fail(f"{path}: resolve_missing() with a prefix this test cannot read; use a string literal")
    assert prefixes, "the scan found no resolve_missing() calls -- the test is broken"
    missing = sorted(prefix for prefix in prefixes if not notifications.is_live(prefix + "x"))
    assert missing == [], f"add these prefixes to LIVE_PREFIXES: {missing}"


# ------------------------------------------------------------------ the decision sticks
def test_a_dismissed_problem_is_not_reopened_by_the_next_check(store):
    _report(store, PRICE)
    store.dismiss(PRICE)
    assert _open(store) == []
    assert _report(store, PRICE) == 0                 # the next check reports the same problem ...
    assert _open(store) == []                          # ... and it stays dismissed


def test_a_plain_resolve_still_reopens_when_the_problem_is_reported_again(store):
    """Unchanged behaviour for resolve(): only dismiss() makes the decision stick."""
    _report(store, PRICE)
    store.resolve(PRICE)
    assert _open(store) == []
    assert _report(store, PRICE) == 1
    assert _open(store) == [PRICE]


def test_when_the_check_stops_reporting_the_problem_the_dismissal_is_forgotten(store):
    _report(store, PRICE)
    store.dismiss(PRICE)
    assert store.resolve_missing("situazione-price-", []) == 0       # completed check: problem gone
    assert _report(store, PRICE) == 1                                # it comes back -> reported again
    assert _open(store) == [PRICE]


def test_a_check_that_still_reports_it_keeps_the_dismissal(store):
    _report(store, PRICE)
    store.dismiss(PRICE)
    store.resolve_missing("situazione-price-", [PRICE])              # still reported
    assert _report(store, PRICE) == 0 and _open(store) == []


def test_a_dismissal_in_another_family_is_untouched_by_a_check_of_this_one(store):
    other = "prezzi-category-missing:X"
    _report(store, other)
    store.dismiss(other)
    store.resolve_missing("situazione-price-", [])
    assert _report(store, other) == 0


def test_changed_values_are_a_different_problem_and_are_reported_as_new(store):
    _report(store, PRICE)
    store.dismiss(PRICE)
    assert _report(store, PRICE_CHANGED) == 1
    assert _open(store) == [PRICE_CHANGED]


def test_a_singleton_key_cleared_by_resolve_can_be_reported_again(store):
    key = "situazione-abbina-pending"
    _report(store, key)
    store.dismiss(key)
    assert _report(store, key) == 0
    store.resolve(key)                                 # the producer: "no more suggestions" -> problem gone
    assert _report(store, key) == 1


def test_dismiss_only_touches_open_notifications_and_legacy_items_are_fine(store):
    store._PATH.write_text('[{"key": "old", "title": "t", "message": "m", "page": "p", "resolved": true}]', encoding="utf-8")
    store.dismiss("old")                               # already resolved: nothing changes, nothing breaks
    store.dismiss("missing")
    assert store.list_open() == [] and _report(store, "old") == 1    # legacy item without the flag re-opens as before
