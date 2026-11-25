"""The in-app update system, pinned.

It is the system of the first release in which updating worked (a short PowerShell helper: back up, copy, write version.txt, start,
roll back), kept deliberately plain: antivirus products judge a PowerShell script by what it contains, and a long script full of
.NET calls, hashing and message boxes was deleted by RAV Endpoint Protection ("Suspicious PowerShell script activity",
Risk.Powershell.Script.Gen.DIYST), so the update never started.

What these tests keep from changing:

* the script itself: its length, the things it must NOT contain (what makes antivirus products suspicious), the old structure that
  the regression tests rely on, and what it does when it is really run with PowerShell (good update, every kind of failure, cancel);
* the version: the GitHub release TAG is the version the program has afterwards - written to version.txt by the helper, read first
  from the external version.txt, never from the archive name;
* the hand-over: the program closes only after the helper wrote its start marker, otherwise it stays open and says why;
* the release ZIP: made by ``build.bat zip`` from the whole program folder, named Planning_v<version>.zip, checked before upload.
"""
import os
import re
import shutil
import subprocess
import sys
import uuid
import zipfile
from pathlib import Path

import pytest

from utility import updater
from utility.updater import UpdateLaunch, helper_not_started_message

ROOT = Path(__file__).resolve().parent.parent

PWSH = shutil.which("pwsh") or os.environ.get("PWSH")
if sys.platform == "win32":
    # the same Windows PowerShell 5.1 that runs the real update on a user's machine
    SHELL = [shutil.which("powershell") or "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    HAS_SHELL = True
else:
    SHELL = [PWSH, "-NoProfile", "-File"]
    HAS_SHELL = bool(PWSH)
needs_shell = pytest.mark.skipif(not HAS_SHELL, reason="needs PowerShell: pwsh (PowerShell 7) on Linux/macOS, powershell.exe on Windows")
# these start a real process named like the program (a renamed copy of `sleep`): Unix only
needs_pwsh = pytest.mark.skipif(sys.platform == "win32" or not PWSH, reason="starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh")


def tree(root: Path) -> dict:
    return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*")) if p.is_file()}


def make_install(root: Path) -> Path:
    install = root / "Program Files" / "Planning"
    (install / "_internal").mkdir(parents=True)
    (install / "Planning.exe").write_bytes(b"OLD-EXE" * 10)
    (install / "version.txt").write_text("1.0.2", encoding="utf-8")
    (install / "_internal" / "python312.dll").write_bytes(b"PYTHON312" * 5000)
    (install / "_internal" / "base_library.zip").write_bytes(b"BASE" * 1000)
    (install / "_internal" / "old_only.pyd").write_bytes(b"OLDONLY")
    (install / "_internal" / "data").mkdir()
    (install / "_internal" / "data" / "map.json").write_text('{"a": 1}', encoding="utf-8")
    return install


def make_release(root: Path, with_dll: bool = True) -> Path:
    release = root / "stage" / "Planning"
    (release / "_internal").mkdir(parents=True)
    (release / "Planning.exe").write_bytes(b"NEW-EXE" * 20)
    (release / "version.txt").write_text("9.9.9", encoding="utf-8")
    if with_dll:
        (release / "_internal" / "python312.dll").write_bytes(b"PYTHON312-NEW" * 5000)
    (release / "_internal" / "base_library.zip").write_bytes(b"BASE" * 1000)
    (release / "_internal" / "new_module.pyd").write_bytes(b"NEWMOD" * 100)
    return release


class Run:
    """Render the script exactly as the updater does, replace only the launcher by a stub and shorten the waits, run it."""

    def __init__(self, tmp_path, release, install, backup=None, mode="run", new_version="9.9.9", **timing):
        self.tmp, self.install = tmp_path, install
        self.backup = backup or install.parent / "Planning_Backup"
        self.zip_path = tmp_path / "release.zip"
        self.zip_path.write_bytes(b"zip")
        self.notice, self.started, self.cancel = tmp_path / "update_failed.txt", tmp_path / "started.txt", tmp_path / "cancel.txt"
        timing = {"initial_delay": 0, "exit_checks": 1, "exit_interval": 0, "copy_attempts": 2, "copy_interval": 0,
                  "start_checks": 2, "start_interval": 1, **timing}
        script = updater.build_update_script(
            source_dir=release, install_dir=install, backup_dir=self.backup, exe_path=install / "Planning.exe", new_version=new_version,
            zip_path=self.zip_path, stage_root=release.parent, notice_path=self.notice, started_path=self.started,
            cancel_path=self.cancel, **timing)
        # the script looks for the program by process name: use a name of its own so that tests running at the same
        # time (or a real Planning) cannot be mistaken for the program under test
        self.process_name = "pln" + uuid.uuid4().hex[:8]
        script, replaced = re.subn(r"Get-Process -Name '[^']*'(?:,'[^']*')*", f"Get-Process -Name '{self.process_name}'", script)
        assert replaced == 2, replaced                          # the wait for the old process to exit, and the start check
        self.script = self._stub_launcher(script, mode)
        self.script_path = tmp_path / "update.ps1"
        self.script_path.write_text(self.script, encoding="utf-8")
        self.launched, self.pidfile = tmp_path / "launched.txt", tmp_path / "pid.txt"
        (tmp_path / "bin").mkdir(exist_ok=True)
        fake = tmp_path / "bin" / self.process_name
        if sys.platform != "win32" and not fake.exists():
            fake.symlink_to(shutil.which("sleep"))

    def _stub_launcher(self, script, mode):
        start = script.index("function Start-Planning {")
        end = script.index("\ntry {", start)
        launched, pidfile, fake = self.tmp / "launched.txt", self.tmp / "pid.txt", self.tmp / "bin" / self.process_name
        body = f"function Start-Planning {{\n    Add-Content -LiteralPath '{launched}' -Value 'launch'\n"
        if mode == "run":      # a process with the program's name really runs, like the new program would
            body += (f"    $p = Start-Process -FilePath '{fake}' -ArgumentList '40' -PassThru\n"
                     f"    Set-Content -LiteralPath '{pidfile}' -Value $p.Id\n    return $true\n}}")
        else:                   # the launch "works" but nothing ever runs (a program that crashes at once)
            body += "    return $true\n}"
        return script[:start] + body + script[end:]

    def go(self):
        env = dict(os.environ, TEMP=str(self.tmp / "tmp"))
        (self.tmp / "tmp").mkdir(exist_ok=True)
        try:
            self.proc = subprocess.run([*SHELL, str(self.script_path)], capture_output=True, text=True, env=env, timeout=240)
        finally:
            if self.pidfile.exists():
                try:
                    os.kill(int(self.pidfile.read_text().strip()), 9)
                except (ProcessLookupError, ValueError):
                    pass
        log = self.tmp / "tmp" / "Planning_Update.log"
        raw = log.read_bytes() if log.exists() else b""
        self.log = raw.decode("utf-16" if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else "utf-8", errors="replace")
        self.launches = self.launched.read_text().count("launch") if self.launched.exists() else 0
        return self


def _render(**overrides):
    values = dict(source_dir=Path("/s"), install_dir=Path("/i"), backup_dir=Path("/b"), exe_path=Path("/i/Planning.exe"),
                  new_version="1.2.3", zip_path=Path("/z.zip"), stage_root=Path("/st"))
    values.update(overrides)
    return updater.build_update_script(**values)


# ------------------------------------------------------------------ the script: small and plain (what antivirus products look at)
def test_the_script_stays_small_and_has_the_old_structure():
    script = _render()
    code = [line for line in script.splitlines() if line.strip() and not line.strip().startswith("#")]
    assert len(code) <= 130, f"{len(code)} lines of code: the update helper must stay small (the long one was removed by an antivirus)"
    assert len(script) < 12_000
    for needed in ("Restore-Backup", "Start-Planning", "$backup", "sawRunning", "rolling back to the previous version",
                   "Copy-Item -LiteralPath $_.FullName -Destination $backup", "Get-Process -Name 'Planning'", "Shell.Application"):
        assert needed in script, needed
    assert script.count("Restore-Backup") == 4                          # 1 definition + 3 call sites (copy failed / never started / any error)
    assert "@@" not in script                                           # every placeholder was filled


@pytest.mark.parametrize("forbidden", [
    "Add-Type", "System.Windows.Forms", "MessageBox", "Get-FileHash", "[System.IO.File]", "[System.Text", "[System.Convert]",
    "FromBase64String", "DownloadString", "DownloadFile", "Invoke-WebRequest", "Invoke-Expression", "iex ", "Net.WebClient",
    "-EncodedCommand", "-enc ", "System.Reflection", "VirtualAlloc", "Invoke-Command", "Set-ExecutionPolicy",
])
def test_the_script_contains_nothing_an_antivirus_treats_as_suspicious(forbidden):
    assert forbidden.lower() not in _render().lower()


def test_the_launch_arguments_are_the_working_ones():
    """_run_update_script is unchanged from the release in which updating worked."""
    captured = {}
    import subprocess as sp
    original = sp.Popen
    sp.Popen = lambda args, **kwargs: captured.update(args=args, kwargs=kwargs)
    try:
        updater._run_update_script(Path("update.ps1"), 123, elevated=False)
    finally:
        sp.Popen = original
    assert captured["args"][:2] == ["powershell.exe", "-NoProfile"] and "-File" in captured["args"] and captured["args"][-1] == "update.ps1"
    assert captured["kwargs"]["creationflags"] == 123


def test_the_script_file_is_written_with_a_byte_order_mark_so_non_ascii_paths_survive(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_needs_elevation", lambda directory: False)
    written = []
    monkeypatch.setattr(updater, "_run_update_script", lambda path, flags, elevated: written.append(Path(path).read_bytes()))
    install = tmp_path / "برنامج" / "Planning"                          # a user / folder name in Arabic
    shutil.copytree(make_install(tmp_path / "x"), install)
    archive = _zip(make_release(tmp_path / "y"), tmp_path / "Planning.zip")
    launch = updater.install_update(archive, install, "2.0.0")
    shutil.rmtree(launch.stage_root, ignore_errors=True)
    raw = written[0]
    assert raw.startswith(b"\xef\xbb\xbf")                              # Windows PowerShell 5.1 reads a BOM-less script as ANSI
    assert "برنامج" in raw.decode("utf-8-sig")


# ------------------------------------------------------------------ the script, really run
@needs_pwsh
def test_a_good_update_installs_every_file_keeps_a_complete_backup_writes_the_tag_and_cleans_up(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    run = Run(tmp_path, release, install).go()
    now = tree(install)
    assert now["Planning.exe"] == b"NEW-EXE" * 20
    assert now["_internal/python312.dll"] == b"PYTHON312-NEW" * 5000 and now["_internal/new_module.pyd"] == b"NEWMOD" * 100
    assert now["_internal/data/map.json"] == original["_internal/data/map.json"]            # files the new version does not ship stay
    version = now["version.txt"]
    assert version.strip() == b"9.9.9" and not version.startswith(b"\xef\xbb\xbf")           # the tag, with no byte order mark
    assert tree(run.backup) == original, "the backup must be an exact copy of the version that was replaced"
    assert run.started.exists() and run.launches == 1 and "rolling back" not in run.log
    assert not run.notice.exists()
    assert not release.exists() and not run.zip_path.exists() and not run.script_path.exists()


@needs_pwsh
def test_a_good_update_removes_the_note_of_an_earlier_failed_one(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    (tmp_path / "update_failed.txt").write_text("version=0.0.1\nreason=old\n")
    Run(tmp_path, release, install).go()
    assert not (tmp_path / "update_failed.txt").exists()


@needs_pwsh
def test_the_tag_is_what_the_program_reports_afterwards(tmp_path, monkeypatch):
    install = make_install(tmp_path)
    Run(tmp_path, make_release(tmp_path), install, new_version="3.1.4").go()
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Planning.exe"))
    assert updater.get_installed_version() == "3.1.4"
    assert updater.is_newer_version("3.1.4", updater.get_installed_version()) is False
    assert updater.is_newer_version("3.1.5", updater.get_installed_version()) is True
    assert updater.is_newer_version("3.1.10", updater.get_installed_version()) is True       # numbers, not text


@needs_shell
def test_when_the_backup_cannot_be_made_the_installation_is_left_exactly_as_it_was(tmp_path):
    """The failure that broke a real installation: a backup that fails must cancel the update, not trigger a 'restore'."""
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("a file where the backup folder would have to go", encoding="utf-8")
    run = Run(tmp_path, release, install, backup=blocker / "Planning_Backup", mode="none").go()
    assert tree(install) == original                                   # every file, byte for byte
    assert "nothing is deleted" in run.log and run.launches == 1       # the old program was started again
    note = run.notice.read_text(encoding="utf-8-sig")
    assert "version=9.9.9" in note and "reason=" in note


@needs_shell
def test_a_backup_that_is_incomplete_is_not_used_for_a_rollback(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    run = Run(tmp_path, release, install, mode="none")
    # the backup loses a file right after it was made: it is smaller than the installation, so the update is cancelled
    run.script = run.script.replace("$inBackup = @(", "Get-ChildItem -LiteralPath $backup -Recurse -Force -File | Select-Object -First 1 | Remove-Item -Force\n    $inBackup = @(", 1)
    run.script_path.write_text(run.script, encoding="utf-8")
    run.go()
    assert tree(install) == original and "incomplete" in run.log
    assert "reason=" in run.notice.read_text(encoding="utf-8-sig")


@needs_shell
def test_a_copy_that_never_succeeds_rolls_back_to_the_exact_previous_installation(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    (release / "_internal" / "data").write_text("a FILE where the installed version has a FOLDER", encoding="utf-8")   # cannot be copied over
    original = tree(install)
    run = Run(tmp_path, release, install, mode="none").go()
    assert tree(install) == original
    assert "rolling back to the previous version" in run.log and run.launches == 1
    note = run.notice.read_text(encoding="utf-8-sig")
    assert "version=9.9.9" in note and "could not be copied" in note and "Planning_Update.log" in note


@needs_shell
def test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    run = Run(tmp_path, release, install, mode="none").go()            # the launch is accepted, but no Planning process appears
    assert tree(install) == original                                   # the new version's files are gone again, byte for byte
    assert "never started running" in run.log and run.launches == 2                           # the new one, then the old one
    assert "did not start" in run.notice.read_text(encoding="utf-8-sig")


@needs_shell
def test_an_unexpected_error_still_ends_with_the_old_program_started_and_a_note(tmp_path):
    install = make_install(tmp_path)
    run = Run(tmp_path, make_release(tmp_path), install, mode="none")
    shutil.rmtree(install)                                             # the installation folder disappears under the helper
    run.go()
    assert run.launches == 1 and run.notice.exists()


# ------------------------------------------------------------------ cancel / start marker
@needs_shell
def test_the_helper_writes_its_start_marker_first_and_a_cancelled_one_changes_nothing(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    before = tree(install)
    (tmp_path / "cancel.txt").write_text("cancelled")
    run = Run(tmp_path, release, install).go()
    assert run.started.exists()                                        # it did start (late) ...
    assert tree(install) == before and run.launches == 0               # ... and left the installation alone, no second program
    assert "withdrew this update" in run.log
    assert not release.exists() and not run.zip_path.exists() and not run.script_path.exists()
    assert not run.backup.exists()


# ------------------------------------------------------------------ the hand-over (the program waits for the helper)
def _launch(tmp_path, elevated=False):
    stage = tmp_path / "stage_x"
    stage.mkdir(exist_ok=True)
    return UpdateLaunch(stage / "helper_started.txt", stage / "helper_cancel.txt", stage, tmp_path / "Planning_Update_1.ps1", elevated)


class FakeTime:
    def __init__(self):
        self.now, self.sleeps = 0.0, []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def test_the_launch_is_confirmed_as_soon_as_the_helper_writes_its_marker(tmp_path):
    launch, fake, pumped = _launch(tmp_path), FakeTime(), []

    def sleep_then_create(seconds):
        fake.sleep(seconds)
        if len(fake.sleeps) == 3:
            launch.started_marker.write_text("started")

    assert launch.wait_until_started(pump=lambda: pumped.append(1), sleep=sleep_then_create, clock=fake.clock) is True
    assert len(fake.sleeps) == 3 and len(pumped) == 3


def test_a_helper_that_never_starts_is_given_up_after_the_timeout_and_the_window_is_pumped(tmp_path):
    launch, fake, pumped = _launch(tmp_path), FakeTime(), []
    assert launch.wait_until_started(pump=lambda: pumped.append(1), sleep=fake.sleep, clock=fake.clock) is False
    assert fake.now >= updater.HELPER_START_TIMEOUT_SECONDS and pumped


def test_the_wait_is_longer_behind_the_windows_permission_prompt(tmp_path):
    assert _launch(tmp_path, False).timeout == updater.HELPER_START_TIMEOUT_SECONDS
    assert _launch(tmp_path, True).timeout == updater.HELPER_START_TIMEOUT_ELEVATED_SECONDS > updater.HELPER_START_TIMEOUT_SECONDS


def test_cancel_writes_the_withdrawal_marker_and_the_message_says_what_to_do(tmp_path):
    launch = _launch(tmp_path, elevated=True)
    launch.cancel()
    assert launch.cancel_marker.exists()
    text = helper_not_started_message(launch)
    assert "nothing was changed" in text and "stays open" in text and "antivirus" in text and "Planning_Update.log" in text


def _zip(release, archive, prefix=""):
    with zipfile.ZipFile(archive, "w") as z:
        for path in release.rglob("*"):
            if path.is_file():
                z.write(path, prefix + path.relative_to(release).as_posix())
    return archive


@pytest.mark.parametrize("prefix", ["", "Planning/", "dist/Planning/"], ids=["flat", "planning-folder", "dist-folder"])
def test_install_update_stages_every_zip_layout_and_hands_the_tag_to_the_helper(tmp_path, monkeypatch, prefix):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_needs_elevation", lambda directory: False)
    scripts = []
    monkeypatch.setattr(updater, "_run_update_script", lambda path, flags, elevated: scripts.append(Path(path).read_text(encoding="utf-8-sig")))
    install = make_install(tmp_path)
    archive = _zip(make_release(tmp_path / "rel"), tmp_path / "Planning.zip", prefix)
    launch = updater.install_update(archive, install, "7.8.9")
    try:
        assert isinstance(launch, UpdateLaunch) and launch.started_marker.parent == launch.stage_root
        script = scripts[0]
        assert "$newVersion = '7.8.9'" in script and str(launch.started_marker) in script and str(launch.cancel_marker) in script
        assert script.index("helper_started.txt") < script.index("Start-Sleep")                      # the marker comes before any waiting
        assert (install / "version.txt").read_text() == "1.0.2"                                      # nothing was touched yet
    finally:
        shutil.rmtree(launch.stage_root, ignore_errors=True)


@pytest.mark.parametrize("files, expected", [
    ({"Planning.exe": b"x"}, "Python DLL is missing"),
    ({"Planning.exe": b"x", "_internal/other.dll": b"x"}, "Python DLL is missing"),
    ({"Planning.exe": b"", "_internal/python312.dll": b"x"}, "must contain Planning.exe"),
    ({"readme.txt": b"x"}, "must contain Planning.exe"),
], ids=["exe-only", "no-python-dll", "empty-exe", "no-exe"])
def test_an_incomplete_package_is_refused_before_anything_changes(tmp_path, monkeypatch, files, expected):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_needs_elevation", lambda directory: False)
    started = []
    monkeypatch.setattr(updater, "_run_update_script", lambda *a: started.append(1))
    install = make_install(tmp_path)
    before = tree(install)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    with pytest.raises(RuntimeError, match=expected) as caught:
        updater.install_update(archive, install, "2.0.0")
    assert started == [] and tree(install) == before and not archive.exists()                # the helper was never started
    if "DLL" in expected:
        assert "build.bat zip" in str(caught.value)                                          # says what to upload instead


def test_the_installer_asset_is_the_planning_zip_whatever_its_name_or_the_listing_order():
    pick = updater._choose_installer
    assert pick([{"name": "notes.zip", "browser_download_url": "u1"}, {"name": "Planning_v1.3.8.zip", "browser_download_url": "u2"}]) == ("Planning_v1.3.8.zip", "u2")
    assert pick([{"name": "log.zip", "browser_download_url": "u1"}, {"name": "Planning.zip", "browser_download_url": "u2"}]) == ("Planning.zip", "u2")
    assert pick([{"name": "PLANNING_V2.ZIP", "browser_download_url": "u1"}, {"name": "a.zip", "browser_download_url": "u2"}])[1] == "u1"
    assert pick([{"name": "only.zip", "browser_download_url": "u"}]) == ("only.zip", "u")
    assert pick([{"name": "notes.txt", "browser_download_url": "u"}]) == ("", "")


# ------------------------------------------------------------------ the version (tag = installed version)
class _Response:
    def __init__(self, payload):
        import json
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.mark.parametrize("tag, installed, offered", [("v1.3.7", "1.3.6", True), ("v1.3.7", "1.3.7", False), ("v1.3.7", "1.4.0", False),
                                                       ("1.3.10", "1.3.9", True), ("v2.0.0", "1.99.99", True)])
def test_the_latest_release_tag_is_the_version_offered(monkeypatch, tag, installed, offered):
    payload = {"tag_name": tag, "name": "R", "body": "", "html_url": "h",
               "assets": [{"name": "Planning_v9.9.9.zip", "browser_download_url": "https://example/Planning.zip"}]}
    monkeypatch.setattr(updater, "urlopen", lambda request, timeout=0: _Response(payload))
    monkeypatch.setattr(updater, "get_installed_version", lambda: installed)
    release = updater.fetch_latest_release()
    assert (release is not None) is offered
    if offered:
        assert release.version == tag.lstrip("vV") and release.tag_name == tag          # the tag, not the number in the file name


def test_the_external_version_file_wins_and_a_byte_order_mark_does_no_harm(tmp_path, monkeypatch):
    install = tmp_path / "app"
    (install / "_internal").mkdir(parents=True)
    (install / "Planning.exe").write_bytes(b"x")
    (install / "_internal" / "version.txt").write_text("1.3.6\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Planning.exe"))
    assert updater.get_installed_version() == "1.3.6"                                   # a fresh build: only the bundled copy
    (install / "version.txt").write_bytes(b"\xef\xbb\xbf1.3.7\r\n")                    # what Windows PowerShell 5.1 "UTF8" writes
    assert updater.get_installed_version() == "1.3.7"


def test_write_version_file_writes_the_plain_version_and_verifies_it(tmp_path):
    path = updater.write_version_file("v1.4.2", tmp_path / "v" / "version.txt")
    assert path.read_bytes() == b"1.4.2\n"


def test_the_failure_note_is_read_once_and_removed(tmp_path):
    note = tmp_path / "update_failed.txt"
    note.write_bytes(b"\xef\xbb\xbfversion=1.3.8\r\nreason=the copy never succeeded\r\nlog=C:\\Temp\\Planning_Update.log\r\n")
    text = updater.consume_update_failure_notice(note)
    assert "1.3.8" in text and "was NOT installed" in text and "the copy never succeeded" in text and "Planning_Update.log" in text
    assert not note.exists() and updater.consume_update_failure_notice(note) is None
    assert updater.consume_update_failure_notice(tmp_path / "missing.txt") is None


# ------------------------------------------------------------------ the release ZIP (dist) and the files that describe it
def _build_bat():
    return (ROOT / "build.bat").read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")


def test_build_bat_makes_the_release_zip_only_on_request_from_the_whole_program_folder():
    text = _build_bat()
    assert 'if /i "%~1"=="zip" (' in text
    assert "Compress-Archive -Path 'dist\\Planning\\*' -DestinationPath 'dist\\Planning_v!PLANNING_VERSION!.zip' -Force" in text
    assert 'for /f "usebackq tokens=*" %%V in ("version.txt") do set "PLANNING_VERSION=%%V"' in text
    block = text[text.index('if /i "%~1"=="zip" ('):text.index("echo  ================================================\necho    Build Complete!")]
    assert 'tools\\check_release_zip.py "dist\\Planning_v!PLANNING_VERSION!.zip"' in block         # incomplete ZIPs never get through
    assert block.index("Compress-Archive") < block.index("check_release_zip.py") < block.index("ZIP_NOTE=")
    assert "Planning.zip" not in text
    assert (ROOT / "tools" / "check_release_zip.py").is_file()


def test_build_bat_keeps_to_windows_batch_rules():
    raw = (ROOT / "build.bat").read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n"), "build.bat must keep CRLF line endings"
    assert b"enabledelayedexpansion" in raw.lower()                                                  # !PLANNING_VERSION! needs it


def test_the_release_steps_describe_this_system():
    text = (ROOT / "docs" / "RELEASE_STEPS.md").read_text(encoding="utf-8")
    for needed in ("build.bat zip", "Planning_v", "tag", "check_release_zip.py", "RAV"):
        assert needed in text, needed


def test_the_version_files_agree():
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert updater.DEFAULT_APP_VERSION == version
    assert f'#define AppVersion   "{version}"' in (ROOT / "installer.iss").read_text(encoding="utf-8")
