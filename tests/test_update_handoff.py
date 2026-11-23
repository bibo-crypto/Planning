"""The program must not close until the update helper has proved it is running, and the helper must tell the user when it fails.

The incident: antivirus (or a Windows policy) stopped the update, the program had already closed itself, and the user saw nothing - no
message, no program.  Now: (1) the helper writes a marker as its very first act and the program waits for it; (2) without it the program
stays open, withdraws the update and says why; (3) a helper that starts late finds the withdrawal and touches nothing; (4) when the helper
rolls back or fails it shows a Windows message instead of leaving only a note for the next start.
"""
import sys
import tkinter as tk
from pathlib import Path
from tkinter import messagebox, ttk

import pytest

from tests.test_startup_pages import start_app                      # noqa: F401  (fixture)
from tests.test_update_script import Run, make_install, make_release, needs_pwsh, needs_shell, tree
from utility import updater
from utility.updater import UpdateLaunch, helper_not_started_message


def _launch(tmp_path, elevated=False):
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    return UpdateLaunch(stage / "helper_started.txt", stage / "helper_cancel.txt", stage, tmp_path / "Planning_UpdateBootstrap_1.ps1", elevated)


class FakeTime:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


# ------------------------------------------------------------------ the handshake
def test_the_launch_is_confirmed_as_soon_as_the_helper_writes_its_marker(tmp_path):
    launch, fake, pumped = _launch(tmp_path), FakeTime(), []
    real_sleep = fake.sleep

    def sleep_then_create(seconds):
        real_sleep(seconds)
        if len(fake.sleeps) == 3:
            launch.started_marker.write_text("started")

    assert launch.wait_until_started(pump=lambda: pumped.append(1), sleep=sleep_then_create, clock=fake.clock) is True
    assert len(fake.sleeps) == 3 and len(pumped) == 3               # the window was pumped on every poll


def test_a_helper_that_never_starts_is_given_up_after_the_timeout(tmp_path):
    launch, fake, pumped = _launch(tmp_path), FakeTime(), []
    assert launch.wait_until_started(pump=lambda: pumped.append(1), sleep=fake.sleep, clock=fake.clock) is False
    assert fake.now >= updater.HELPER_START_TIMEOUT_SECONDS and pumped


def test_the_wait_is_longer_behind_the_windows_permission_prompt(tmp_path):
    assert _launch(tmp_path, elevated=False).timeout == updater.HELPER_START_TIMEOUT_SECONDS
    assert _launch(tmp_path, elevated=True).timeout == updater.HELPER_START_TIMEOUT_ELEVATED_SECONDS > updater.HELPER_START_TIMEOUT_SECONDS


def test_the_marker_already_there_means_no_waiting_at_all(tmp_path):
    launch, fake = _launch(tmp_path), FakeTime()
    launch.started_marker.write_text("started")
    assert launch.wait_until_started(sleep=fake.sleep, clock=fake.clock) is True and fake.sleeps == []


def test_cancel_writes_the_withdrawal_marker_and_the_message_says_what_to_do(tmp_path):
    launch = _launch(tmp_path, elevated=True)
    launch.cancel()
    assert launch.cancel_marker.exists()
    text = helper_not_started_message(launch)
    assert "nothing was changed" in text and "stays open" in text and "antivirus" in text and "Planning_Update.log" in text
    assert "permission prompt was not approved" in text


def test_install_update_returns_the_launch_with_markers_inside_the_stage_folder(tmp_path, monkeypatch):
    import zipfile
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    scripts = []
    monkeypatch.setattr(updater, "_run_update_script", lambda path, flags, elevated: scripts.append(Path(path).read_text(encoding="utf-8")))
    release = make_release(tmp_path)
    archive = tmp_path / "Planning.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in release.rglob("*"):
            if path.is_file():
                z.write(path, path.relative_to(release).as_posix())
    launch = updater.install_update(archive, make_install(tmp_path), "7.8.9")
    assert isinstance(launch, UpdateLaunch) and launch.started_marker.parent == launch.stage_root == launch.cancel_marker.parent
    assert launch.started_marker.name == "helper_started.txt" and launch.cancel_marker.name == "helper_cancel.txt"
    assert str(launch.started_marker) in scripts[0] and str(launch.cancel_marker) in scripts[0]
    assert scripts[0].index("helper_started.txt") < scripts[0].index("Write-UpdateLog (\"Update helper started")      # the marker comes FIRST
    updater.shutil.rmtree(launch.stage_root, ignore_errors=True)


# ------------------------------------------------------------------ the helper itself (real PowerShell)
@needs_pwsh
def test_the_helper_writes_the_marker_before_anything_else_and_a_good_update_shows_no_message(tmp_path):
    run = Run(tmp_path, make_release(tmp_path), make_install(tmp_path)).go()
    assert run.started.exists() and run.launches == 1
    assert not run.message_file.exists()


@needs_shell
def test_a_helper_that_finds_the_cancel_marker_changes_nothing_and_cleans_up(tmp_path):
    install = make_install(tmp_path)
    before = tree(install)
    release = make_release(tmp_path)
    stage = release.parent
    (tmp_path / "cancel.txt").write_text("cancelled")
    run = Run(tmp_path, release, install).go()
    assert run.started.exists()                                  # it did start (late) ...
    assert tree(install) == before and run.launches == 0         # ... and left the installation alone, no second program
    assert "withdrew this update" in run.log
    assert not stage.exists() and not (tmp_path / "release.zip").exists() and not run.script_path.exists()
    assert not run.message_file.exists()


@needs_shell
def test_a_rollback_shows_a_message_with_the_reason_the_state_and_the_log(tmp_path):
    install = make_install(tmp_path)
    run = Run(tmp_path, make_release(tmp_path), install, mode="none").go()          # the new program never starts
    text = run.message_file.read_text()
    assert "could not be updated to 9.9.9" in text and "did not start" in text and "antivirus" in text
    assert "previous version was restored" in text and "Planning_Update.log" in text
    assert (install / "version.txt").read_text() == "1.0.2"                          # and it really is restored


@needs_shell
def test_an_unexpected_error_also_ends_with_a_message(tmp_path):
    install = make_install(tmp_path)
    run = Run(tmp_path, make_release(tmp_path), install)
    updater.shutil.rmtree(install)                               # the installation folder disappears under the helper
    run.go()
    text = run.message_file.read_text()
    assert "could not be updated to 9.9.9" in text and "Details:" in text and "Planning_Update.log" in text
    assert "left exactly as it was" in text                      # no verified backup existed: nothing was touched
    assert (tmp_path / "update_failed.txt").exists()             # the note for the next start is still written


# ------------------------------------------------------------------ the window
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
