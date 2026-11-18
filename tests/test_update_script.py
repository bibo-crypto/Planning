"""The PowerShell helper that replaces the installed files during an in-app update, run for real.

A failed update must never leave the program broken.  Before this was tested, a backup that could not be completed (for
example a file locked by antivirus) made the script wipe the healthy installation and "restore" a partial copy -- the
program then stopped with "Failed to load Python DLL ...\\_internal\\python312.dll".  These tests render the script
exactly as the updater does (only the launcher is replaced by a stub, and the waits are shortened), run it with
PowerShell, and compare the installation folder byte for byte.
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

PWSH = shutil.which("pwsh") or os.environ.get("PWSH")
if sys.platform == "win32":
    # the same Windows PowerShell 5.1 that runs the real update on a user's machine
    SHELL = [shutil.which("powershell") or "powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File"]
    HAS_SHELL = True
else:
    SHELL = [PWSH, "-NoProfile", "-File"]
    HAS_SHELL = bool(PWSH)
needs_shell = pytest.mark.skipif(not HAS_SHELL, reason="needs PowerShell: pwsh (PowerShell 7) on Linux/macOS, powershell.exe on Windows")
# the "good update" test starts a real process named like the program (a renamed copy of `sleep`): Unix only
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
    def __init__(self, tmp_path, release, install, backup=None, mode="run", **timing):
        self.tmp, self.install = tmp_path, install
        self.backup = backup or install.parent / "Planning_Backup"
        zip_path = tmp_path / "release.zip"
        zip_path.write_bytes(b"zip")
        timing = {"initial_delay": 0, "exit_checks": 1, "exit_interval": 0, "attempts": 2, "retry_delay": 0,
                  "start_checks": 2, "start_interval": 1, **timing}
        script = updater.build_update_script(source_dir=release, install_dir=install, backup_dir=self.backup,
                                             exe_path=install / "Planning.exe", new_version="9.9.9", zip_path=zip_path,
                                             stage_root=release.parent, **timing)
        # the script looks for the program by process name: use a name of its own so that tests running at the same
        # time (or a real Planning) cannot be mistaken for the program under test
        self.process_name = "pln" + uuid.uuid4().hex[:8]
        script, replaced = re.subn(r"Get-Process -Name '[^']*'(?:,'[^']*')*", f"Get-Process -Name '{self.process_name}'", script)
        assert replaced == 2                                       # the wait for the old process to exit, and the start check
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


# ------------------------------------------------------------------ the update works
@needs_pwsh
def test_a_good_update_installs_every_file_keeps_a_verified_backup_and_cleans_up(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    run = Run(tmp_path, release, install).go()
    now = tree(install)
    assert now["Planning.exe"] == b"NEW-EXE" * 20 and now["version.txt"].decode().strip() == "9.9.9"
    assert now["_internal/python312.dll"] == b"PYTHON312-NEW" * 5000 and now["_internal/new_module.pyd"] == b"NEWMOD" * 100
    assert now["_internal/data/map.json"] == original["_internal/data/map.json"]            # files the new version does not ship stay
    assert tree(run.backup) == original, "the backup must be an exact copy of the version that was replaced"
    assert run.launches == 1 and "Rolled back" not in run.log and "never started" not in run.log
    assert not release.exists() and not (tmp_path / "release.zip").exists() and not run.script_path.exists()


# ------------------------------------------------------------------ nothing is lost when the update cannot start
@needs_shell
def test_when_the_backup_cannot_be_made_the_installation_is_left_exactly_as_it_was(tmp_path):
    """The failure that broke a real installation: a backup that fails must cancel the update, not trigger a 'restore'."""
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    blocker = tmp_path / "not_a_folder"
    blocker.write_text("a file where the backup folder would have to go", encoding="utf-8")
    run = Run(tmp_path, release, install, backup=blocker / "Planning_Backup", mode="none").go()
    assert tree(install) == original                                   # every file, byte for byte
    assert (install / "_internal" / "python312.dll").exists() and (install / "Planning.exe").read_bytes() == b"OLD-EXE" * 10
    assert "No verified backup" in run.log and run.launches == 1       # the old program was started again
    assert "NEW-EXE" not in (install / "Planning.exe").read_text(errors="ignore")


@needs_shell
@pytest.mark.skipif(sys.platform == "win32" or (hasattr(os, "geteuid") and os.geteuid() == 0),
                    reason="needs an unprivileged user: permissions do not bind root (verified by hand with runuser)")
def test_a_file_that_cannot_be_read_while_backing_up_cancels_the_update(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    locked = install / "_internal" / "locked.dll"
    locked.write_bytes(b"x")
    locked.chmod(0)
    try:
        original = {k: v for k, v in tree(install).items() if k != "_internal/locked.dll"}
        run = Run(tmp_path, release, install, mode="none").go()
        assert {k: v for k, v in tree(install).items() if k != "_internal/locked.dll"} == original
        assert locked.exists() and "nothing is deleted" in run.log
    finally:
        locked.chmod(0o600)


@needs_shell
def test_a_copy_that_never_succeeds_rolls_back_to_the_exact_previous_installation(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    (release / "_internal" / "data").write_text("a FILE where the installed version has a FOLDER", encoding="utf-8")   # cannot be copied over
    original = tree(install)
    run = Run(tmp_path, release, install, mode="none").go()
    assert tree(install) == original
    assert "rolling back" in run.log and "Rolled back to the previous version (verified)" in run.log and run.launches == 1


@needs_shell
def test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched(tmp_path):
    install, release = make_install(tmp_path), make_release(tmp_path)
    original = tree(install)
    run = Run(tmp_path, release, install, mode="none").go()            # the launch is accepted, but no Planning process appears
    assert tree(install) == original                                   # files only the new version had are removed again
    assert "never started running" in run.log and "Rolled back to the previous version (verified)" in run.log
    assert run.launches == 2                                           # the new one, then the old one


@needs_shell
def test_a_rollback_that_cannot_be_completed_says_so_and_deletes_nothing_more(tmp_path):
    """Everything copied back is checked against the list of the previous version made BEFORE the update; if a file is
    missing (here: the backup lost one after it was verified) the log names it, the backup stays and nothing else is removed."""
    install, release = make_install(tmp_path), make_release(tmp_path)
    run = Run(tmp_path, release, install, mode="none")
    run.script = run.script.replace('$script:backupVerified = $true',
                                    '$script:backupVerified = $true\n    Remove-Item -LiteralPath (Join-Path $backup "_internal/python312.dll") -Force', 1)
    run.script_path.write_text(run.script, encoding="utf-8")
    run.go()
    assert "Rollback incomplete" in run.log and "python312.dll" in run.log.lower()
    assert (run.backup / "Planning.exe").exists()                       # the backup is kept for a manual recovery
    assert (install / "_internal" / "new_module.pyd").exists()          # files of the new version are NOT cleaned up after an unverified rollback
    assert (install / "_internal" / "python312.dll").exists()           # and no file is deleted while the rollback cannot be proven complete


# ------------------------------------------------------------------ a broken package never reaches the installation
def _frozen(monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(updater, "_needs_elevation", lambda directory: False)


def test_an_update_package_without_the_python_dll_is_refused_before_anything_changes(tmp_path, monkeypatch):
    _frozen(monkeypatch)
    launched = []
    monkeypatch.setattr(updater, "_run_update_script", lambda *a, **k: launched.append(a))
    install = make_install(tmp_path)
    original = tree(install)
    broken = make_release(tmp_path, with_dll=False)
    archive = tmp_path / "broken.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in broken.rglob("*"):
            if path.is_file():
                z.write(path, "Planning/" + path.relative_to(broken).as_posix())
    with pytest.raises(RuntimeError, match="Python DLL is missing"):
        updater.install_update(archive, install, "9.9.9")
    assert launched == [] and tree(install) == original


def test_a_complete_package_is_accepted_and_the_script_is_started(tmp_path, monkeypatch):
    _frozen(monkeypatch)
    started = []
    monkeypatch.setattr(updater, "_run_update_script", lambda path, flags, elevated: started.append(Path(path).read_text(encoding="utf-8")))
    install = make_install(tmp_path)
    good = make_release(tmp_path)
    archive = tmp_path / "good.zip"
    with zipfile.ZipFile(archive, "w") as z:
        for path in good.rglob("*"):
            if path.is_file():
                z.write(path, "Planning/" + path.relative_to(good).as_posix())
    updater.install_update(archive, install, "9.9.9")
    assert len(started) == 1 and "Find-MissingFiles" in started[0] and "$script:backupVerified = $true" in started[0]
