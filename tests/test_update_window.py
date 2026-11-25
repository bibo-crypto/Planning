"""The window side of an update: the program closes only after the update helper confirmed it is running; otherwise it stays
open, withdraws the update and says why (the incident: antivirus removed the helper and the program just disappeared)."""
from tkinter import messagebox, ttk

import pytest

from tests.test_startup_pages import start_app                      # noqa: F401,F811  (fixture)
from tests.test_update_system import _launch
from utility import updater


class Exit(BaseException):
    pass


def _prepare_window(app, monkeypatch, launch):
    app._update_status = ttk.Label(app)
    app._update_progress_bar = ttk.Progressbar(app)
    app._update_window = None
    app._pending_update_version = "7.8.9"
    from gui import gui as gui_module
    monkeypatch.setattr(gui_module, "install_update", lambda *args: launch)
    monkeypatch.setattr(updater, "HELPER_START_TIMEOUT_SECONDS", 0.4)
    monkeypatch.setattr(updater, "HELPER_POLL_SECONDS", 0.02)
    errors, exits = [], []
    monkeypatch.setattr(messagebox, "showerror", lambda *a, **k: errors.append(a))

    def fake_exit(code):
        exits.append(code)
        raise Exit

    monkeypatch.setattr(gui_module.os, "_exit", fake_exit)
    monkeypatch.setattr(app, "destroy", lambda: None)            # the fixture owns the window
    return errors, exits


def test_the_program_stays_open_and_explains_when_the_helper_never_starts(start_app, monkeypatch, tmp_path):
    app, _errors, _shown = start_app()
    launch = _launch(tmp_path)
    errors, exits = _prepare_window(app, monkeypatch, launch)
    app._finish_update(tmp_path / "Planning.zip")
    assert exits == []                                           # it did NOT close itself
    assert len(errors) == 1 and "stays open" in errors[0][1] and "nothing was changed" in errors[0][1]
    assert launch.cancel_marker.exists()                         # a late helper is told to do nothing


def test_the_program_closes_only_after_the_helper_has_confirmed(start_app, monkeypatch, tmp_path):
    app, _errors, _shown = start_app()
    launch = _launch(tmp_path)
    launch.started_marker.write_text("started")
    errors, exits = _prepare_window(app, monkeypatch, launch)
    with pytest.raises(Exit):
        app._finish_update(tmp_path / "Planning.zip")
    assert exits == [0] and errors == [] and not launch.cancel_marker.exists()
