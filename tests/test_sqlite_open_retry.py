"""Opening a SQLite connection survives a transient "disk I/O error" / "database is locked".

The user's converter.log shows ``sqlite3.OperationalError: disk I/O error`` raised while the connection of
``situazione_db.get_conn`` was being opened (``PRAGMA synchronous=NORMAL``).  ``init_db`` retried, but ``get_conn``,
``orders_db._connect`` and ``prezzi_db._connect`` did not.  The fake connections below fail exactly where the log
says (the connect itself, or the first statement run on the new connection).
"""
import logging
import sqlite3

import pytest

from utility import orders_db, prezzi_db, situazione_db, sqlite_retry


class FlakyConnection:
    """A real connection whose ``execute`` raises *error* when the SQL contains *fail_on* (until told otherwise)."""

    def __init__(self, real, fail_on, error, log):
        self._real, self._fail_on, self._error, self.closed = real, fail_on, error, False
        self._log = log

    def execute(self, sql, *args):
        if self._fail_on and self._fail_on in sql:
            self._log.append(("execute-failed", sql.split()[0]))
            raise self._error
        return self._real.execute(sql, *args)

    def close(self):
        self.closed = True
        self._real.close()

    def __getattr__(self, name):                       # commit, cursor, ... go to the real connection
        return getattr(self._real, name)

    def __setattr__(self, name, value):
        if name == "row_factory":
            self._real.row_factory = value
        else:
            object.__setattr__(self, name, value)


class Flaky:
    """Replaces ``sqlite3.connect``: the first *failures* connections fail (at connect, or at statement *fail_on*)."""

    def __init__(self, monkeypatch, failures, error, where, fail_on=None):
        self.error, self.where, self.fail_on = error, where, fail_on
        self.failures, self.connects, self.opened, self.log = failures, 0, [], []
        self._real_connect = sqlite3.connect
        monkeypatch.setattr(sqlite3, "connect", self)

    def __call__(self, *args, **kwargs):
        self.connects += 1
        failing = self.connects <= self.failures
        if failing and self.where == "connect":
            self.log.append(("connect-failed", None))
            raise self.error
        conn = FlakyConnection(self._real_connect(*args, **kwargs), self.fail_on if failing and self.where == "statement" else None,
                               self.error, self.log)
        self.opened.append(conn)
        return conn


# (name, how to open one, the statement that runs first on the new connection and is made to fail)
OPENERS = [
    pytest.param(lambda tmp: situazione_db.get_conn(), "synchronous", id="situazione_db.get_conn"),
    pytest.param(lambda tmp: orders_db._connect(tmp / "orders.sqlite3"), "CREATE TABLE", id="orders_db._connect"),
    pytest.param(lambda tmp: prezzi_db._connect(tmp / "prezzi.sqlite3"), "CREATE TABLE", id="prezzi_db._connect"),
]
WHERE = ["connect", "statement"]


@pytest.fixture(autouse=True)
def sleeps(monkeypatch, tmp_path):
    waited = []
    monkeypatch.setattr(sqlite_retry.time, "sleep", lambda seconds: waited.append(round(seconds, 3)))
    monkeypatch.setattr(situazione_db, "DB_PATH", str(tmp_path / "situazione.db"))
    return waited


@pytest.mark.parametrize("where", WHERE)
@pytest.mark.parametrize("open_connection, fail_on", OPENERS)
@pytest.mark.parametrize("message", ["disk I/O error", "database is locked"])
def test_a_transient_error_twice_is_retried_and_the_third_attempt_works(
        monkeypatch, tmp_path, sleeps, caplog, open_connection, fail_on, where, message):
    flaky = Flaky(monkeypatch, failures=2, error=sqlite3.OperationalError(message), where=where, fail_on=fail_on)

    with caplog.at_level(logging.WARNING, logger="converter"):
        conn = open_connection(tmp_path)

    assert flaky.connects == 3
    assert conn.execute("SELECT 1").fetchone()[0] == 1, "the connection that was returned must work"
    assert sleeps == [0.2, 0.4]
    warnings = [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING]
    assert len(warnings) == 2 and all(message in w for w in warnings)
    assert [c.closed for c in flaky.opened[:-1]] == [True] * (len(flaky.opened) - 1), "failed attempts must close their connection"
    conn.close()


@pytest.mark.parametrize("where", WHERE)
@pytest.mark.parametrize("open_connection, fail_on", OPENERS)
def test_a_permanent_transient_error_is_raised_after_four_attempts(monkeypatch, tmp_path, sleeps, open_connection, fail_on, where):
    flaky = Flaky(monkeypatch, failures=99, error=sqlite3.OperationalError("disk I/O error"), where=where, fail_on=fail_on)

    with pytest.raises(sqlite3.OperationalError, match="disk I/O error"):
        open_connection(tmp_path)

    assert flaky.connects == 4
    assert sleeps == [0.2, 0.4, 0.6]
    assert all(c.closed for c in flaky.opened), "no connection may be left open after the final failure"


@pytest.mark.parametrize("where", WHERE)
@pytest.mark.parametrize("open_connection, fail_on", OPENERS)
@pytest.mark.parametrize("message", [
    "attempt to write a readonly database", "database disk image is malformed", "unable to open database file",
])
def test_any_other_error_is_raised_at_once_without_retry(monkeypatch, tmp_path, sleeps, caplog, open_connection, fail_on, where, message):
    flaky = Flaky(monkeypatch, failures=99, error=sqlite3.OperationalError(message), where=where, fail_on=fail_on)

    with caplog.at_level(logging.WARNING, logger="converter"), pytest.raises(sqlite3.OperationalError, match=message):
        open_connection(tmp_path)

    assert flaky.connects == 1
    assert sleeps == []
    assert not [r for r in caplog.records if r.levelno == logging.WARNING]
    assert all(c.closed for c in flaky.opened)


def test_an_error_that_is_not_an_operational_error_is_never_retried(monkeypatch, tmp_path, sleeps):
    flaky = Flaky(monkeypatch, failures=99, error=sqlite3.DatabaseError("disk I/O error"), where="connect")

    with pytest.raises(sqlite3.DatabaseError):
        orders_db._connect(tmp_path / "orders.sqlite3")

    assert flaky.connects == 1 and sleeps == []


def test_a_healthy_open_makes_no_extra_attempt_and_sets_up_the_connection(tmp_path, sleeps):
    conn = situazione_db.get_conn()
    try:
        assert conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert conn.row_factory is sqlite3.Row
    finally:
        conn.close()
    orders = orders_db._connect(tmp_path / "orders.sqlite3")
    try:
        assert orders.execute("SELECT name FROM sqlite_master WHERE name='orders'").fetchone() is not None
    finally:
        orders.close()
    assert sleeps == []
