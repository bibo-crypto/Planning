"""The update window opens the standard Setup installer and reports launch errors."""
from pathlib import Path
from tkinter import messagebox, ttk

from tests.test_startup_pages import start_app


def _prepare_window(app):
    app._update_status = ttk.Label(app)
    app._update_progress_bar = ttk.Progressbar(app)
    app._update_window = None
    app._pending_update_version = "1.3.9"


def test_update_window_opens_setup_without_exiting_the_old_app(start_app, monkeypatch, tmp_path):
    app, _errors, _shown = start_app()
    _prepare_window(app)
    from gui import gui as gui_module

    calls = []
    monkeypatch.setattr(gui_module, "launch_installer", lambda *args: calls.append(args))
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *args, **kwargs: errors.append(args))
    installer = tmp_path / "Planning_Setup_v1.3.9.exe"

    app._finish_update(installer)

    assert calls == [(installer, Path(gui_module.sys.executable).resolve().parent)]
    assert errors == []


def test_update_window_reports_when_windows_rejects_setup(start_app, monkeypatch, tmp_path):
    app, _errors, _shown = start_app()
    _prepare_window(app)
    from gui import gui as gui_module

    def reject_setup(*args):
        raise RuntimeError("Windows did not approve the installer.")

    monkeypatch.setattr(gui_module, "launch_installer", reject_setup)
    errors = []
    monkeypatch.setattr(messagebox, "showerror", lambda *args, **kwargs: errors.append(args))

    app._finish_update(tmp_path / "Planning_Setup_v1.3.9.exe")

    assert len(errors) == 1
    assert "Windows did not approve" in errors[0][1]
