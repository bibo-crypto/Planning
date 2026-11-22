"""The Tk root helper: retries transient failures, skips only when there is no display, never hides a real error."""
import tkinter as tk

import pytest

from tests import tk_helpers


@pytest.fixture(autouse=True)
def no_real_sleep(monkeypatch):
    sleeps = []
    monkeypatch.setattr(tk_helpers.time, "sleep", lambda seconds: sleeps.append(seconds))
    return sleeps


def _fail_then_succeed(monkeypatch, failures, message="Can't find a usable init.tcl in the following directories"):
    calls = []
    sentinel = object()

    def fake_tk():
        calls.append(1)
        if len(calls) <= failures:
            raise tk.TclError(message)
        return sentinel

    monkeypatch.setattr(tk_helpers.tk, "Tk", fake_tk)
    return calls, sentinel


@pytest.mark.parametrize("platform", ["win32", "linux"])
def test_a_transient_failure_is_retried_until_it_works(monkeypatch, no_real_sleep, platform):
    monkeypatch.setattr(tk_helpers.sys, "platform", platform)
    monkeypatch.setenv("DISPLAY", ":99")
    calls, sentinel = _fail_then_succeed(monkeypatch, failures=2)

    assert tk_helpers.create_tk_root() is sentinel
    assert len(calls) == 3
    assert no_real_sleep == [tk_helpers.DELAY_SECONDS] * 2


def test_on_windows_a_permanent_failure_raises_the_real_error_and_is_not_skipped(monkeypatch):
    monkeypatch.setattr(tk_helpers.sys, "platform", "win32")
    monkeypatch.delenv("DISPLAY", raising=False)             # irrelevant on Windows: there is always a display
    calls, _ = _fail_then_succeed(monkeypatch, failures=99)

    with pytest.raises(tk.TclError, match="init.tcl"):
        tk_helpers.create_tk_root()
    assert len(calls) == tk_helpers.ATTEMPTS


def test_on_linux_without_display_it_skips_at_once_without_retrying(monkeypatch):
    monkeypatch.setattr(tk_helpers.sys, "platform", "linux")
    monkeypatch.delenv("DISPLAY", raising=False)
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    calls, _ = _fail_then_succeed(monkeypatch, failures=99, message="no display name and no $DISPLAY environment variable")

    with pytest.raises(pytest.skip.Exception):
        tk_helpers.create_tk_root()
    assert len(calls) == 1


def test_on_linux_with_display_a_non_display_error_is_a_real_failure(monkeypatch):
    monkeypatch.setattr(tk_helpers.sys, "platform", "linux")
    monkeypatch.setenv("DISPLAY", ":99")
    calls, _ = _fail_then_succeed(monkeypatch, failures=99)

    with pytest.raises(tk.TclError):
        tk_helpers.create_tk_root()
    assert len(calls) == tk_helpers.ATTEMPTS
