"""Regression tests protecting the full build, installer, and auto-update pipeline."""
from __future__ import annotations

import argparse
import sys
import zipfile
from pathlib import Path


import updater_main
from file_version_info import make_updater_version_info, make_version_info
from utility import updater

ROOT = Path(__file__).resolve().parent.parent


def _make_complete_package(root: Path, marker_bytes: bytes = b"new-exe") -> Path:
    package = root / "Planning"
    (package / "_internal").mkdir(parents=True, exist_ok=True)
    (package / "Planning.exe").write_bytes(marker_bytes)
    (package / "Planing.exe").write_bytes(marker_bytes)
    (package / "PlanningUpdater.exe").write_bytes(b"new-updater")
    (package / "icon.ico").write_bytes(b"ico")
    (package / "version.txt").write_text("1.3.8\n", encoding="ascii", newline="\n")
    (package / "_internal" / "python314.dll").write_bytes(b"python-dll")
    (package / "_internal" / "base_library.zip").write_bytes(b"python-stdlib")
    return package


def _zip_dir(source_dir: Path, target_zip: Path) -> Path:
    with zipfile.ZipFile(target_zip, "w") as archive:
        for path in sorted(source_dir.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source_dir).as_posix())
    return target_zip


# ── Build & packaging scripts ────────────────────────────────────────────────


def test_build_bat_builds_and_validates_planning_zip():
    content = (ROOT / "build.bat").read_text(encoding="utf-8")
    assert 'set "MAIN_SPEC=%~dp0main.spec"' in content
    assert 'set "UPDATER_SPEC=%~dp0updater.spec"' in content
    assert '"%VENV_PY%" -m PyInstaller "%MAIN_SPEC%" --noconfirm' in content
    assert '"%VENV_PY%" -m PyInstaller "%UPDATER_SPEC%" --noconfirm' in content
    assert 'if not exist "dist\\PlanningUpdater.exe"' in content
    assert 'dist\\PlanningUpdater\\PlanningUpdater.exe' not in content
    assert 'copy /y "dist\\PlanningUpdater.exe" "dist\\Planning\\PlanningUpdater.exe"' in content
    assert 'copy /y "version.txt" "dist\\Planning\\version.txt"' in content
    assert 'copy /y "icon.ico" "dist\\Planning\\icon.ico"' in content
    assert 'copy /y "dist\\Planning\\Planning.exe" "dist\\Planning\\Planing.exe"' in content
    assert "dist\\planning.zip" in content
    assert 'tools\\check_release_zip.py "dist\\planning.zip"' in content
    assert 'if /i not "%~1"=="nozip"' in content


def test_release_workflow_publishes_planning_zip():
    content = (ROOT / ".github" / "workflows" / "release.yml").read_text(encoding="utf-8")
    assert 'check_release_zip.py "dist\\planning.zip"' in content
    assert "dist/planning.zip" in content
    assert "find release -name 'planning.zip'" in content


def test_specs_and_version_info_embed_publisher_metadata():
    version_str = (ROOT / "version.txt").read_text(encoding="utf-8").strip().lstrip("vV")
    for info in (make_version_info(), make_updater_version_info()):
        entries = dict((s.name, s.val) for s in info.kids[0].kids[0].kids)
        assert entries["CompanyName"] == "Delta Dyeing S.A.E."
        assert entries["ProductName"] == "Planning"
        assert entries["FileVersion"] == version_str
        assert entries["ProductVersion"] == version_str

    assert "version=make_version_info()" in (ROOT / "main.spec").read_text(encoding="utf-8")
    assert "version=make_updater_version_info()" in (ROOT / "updater.spec").read_text(encoding="utf-8")


def test_installer_iss_preserves_per_user_install_metadata_and_never_changes_antivirus():
    content = (ROOT / "installer.iss").read_text(encoding="utf-8")
    assert "PrivilegesRequired=lowest" in content
    assert "DefaultDirName={localappdata}\\Programs\\{#AppName}" in content
    assert 'Source: "{#SourceDir}\\*"' in content
    assert "VersionInfoCompany={#AppPublisher}" in content
    assert "VersionInfoProductName={#AppName}" in content
    assert "Add-MpPreference" not in content
    assert "powershell.exe" not in content
    assert "VersionInfoDescription=Planning application" in content
    assert '#define AppVersion   "1.3.11"' in content


# ── Updater handoff (utility/updater.py) ─────────────────────────────────────


def test_install_update_launches_staged_copy_so_installed_updater_is_unlocked(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    install_dir = tmp_path / "install"
    install_dir.mkdir()
    (install_dir / "PlanningUpdater.exe").write_bytes(b"updater-binary")
    archive = tmp_path / "planning.zip"
    archive.write_bytes(b"zip-bytes")

    captured = {}

    def fake_start(path, args, elevated):
        captured["path"] = path
        captured["args"] = args
        captured["elevated"] = elevated

    monkeypatch.setattr(updater, "_start_updater", fake_start)

    launch = updater.install_update(archive, install_dir, "1.3.8")
    try:
        assert launch.updater_path.parent == launch.stage_root
        assert launch.updater_path != install_dir / "PlanningUpdater.exe"
        assert launch.updater_path.is_file()
        assert captured["path"] == launch.updater_path
        assert "--zip" in captured["args"]
        assert "--install-dir" in captured["args"]
        assert "--backup-dir" in captured["args"]
        assert "--started-marker" in captured["args"]
    finally:
        import shutil
        shutil.rmtree(launch.stage_root, ignore_errors=True)


def test_consume_update_failure_notice_reads_formats_and_deletes(tmp_path):
    note = tmp_path / "update_failed.txt"
    note.write_text("version=1.3.8\nreason=health check failed\nlog=C:/logs/updater.log\n", encoding="utf-8")
    msg = updater.consume_update_failure_notice(note)
    assert msg is not None
    assert "1.3.8" in msg
    assert "health check failed" in msg
    assert "C:/logs/updater.log" in msg
    assert not note.exists()


# ── Updater execution & rollback (updater_main.py) ───────────────────────────


def test_copy_file_with_retry_renames_locked_exe_and_succeeds(tmp_path, monkeypatch):
    src = tmp_path / "new.exe"
    dst = tmp_path / "PlanningUpdater.exe"
    src.write_bytes(b"new-version")
    dst.write_bytes(b"old-version")

    real_copy2 = updater_main.shutil.copy2
    calls = {"n": 0}

    def flaky_copy2(s, d, *args, **kwargs):
        calls["n"] += 1
        if calls["n"] == 1:
            raise PermissionError("locked by running process")
        return real_copy2(s, d, *args, **kwargs)

    monkeypatch.setattr(updater_main.shutil, "copy2", flaky_copy2)
    updater_main._copy_file_with_retry(src, dst, retries=2, delay=0)

    assert dst.read_bytes() == b"new-version"
    assert any(p.name.startswith("PlanningUpdater.exe.") and p.name.endswith(".old") for p in tmp_path.iterdir())


def test_updater_run_succeeds_end_to_end_and_cleans_zip(tmp_path, monkeypatch):
    install_dir = _make_complete_package(tmp_path / "current", marker_bytes=b"old-exe")
    new_pkg = _make_complete_package(tmp_path / "new", marker_bytes=b"new-exe")
    zip_path = _zip_dir(new_pkg, tmp_path / "planning.zip")
    backup_dir = tmp_path / "backup"
    marker = tmp_path / "started.ok"
    log_file = tmp_path / "updater.log"

    monkeypatch.setattr(updater_main, "launch_and_check", lambda exe, cwd, health, log: True)

    args = argparse.Namespace(
        zip=str(zip_path),
        install_dir=str(install_dir),
        backup_dir=str(backup_dir),
        version="v1.3.8",
        parent_pid=0,
        log=str(log_file),
        started_marker=str(marker),
    )
    rc = updater_main.run(args)
    assert rc == 0
    assert marker.is_file()
    assert (install_dir / "Planning.exe").read_bytes() == b"new-exe"
    assert (install_dir / "version.txt").read_bytes() == b"1.3.8\n"
    assert not zip_path.exists()


def test_updater_run_rolls_back_and_writes_failure_notice_on_health_failure(tmp_path, monkeypatch):
    install_dir = _make_complete_package(tmp_path / "current", marker_bytes=b"old-exe")
    new_pkg = _make_complete_package(tmp_path / "new", marker_bytes=b"broken-exe")
    zip_path = _zip_dir(new_pkg, tmp_path / "planning.zip")
    backup_dir = tmp_path / "backup"
    log_file = tmp_path / "updater.log"

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(updater_main, "launch_and_check", lambda exe, cwd, health, log: False)

    args = argparse.Namespace(
        zip=str(zip_path),
        install_dir=str(install_dir),
        backup_dir=str(backup_dir),
        version="1.3.8",
        parent_pid=0,
        log=str(log_file),
        started_marker=None,
    )
    rc = updater_main.run(args)
    assert rc == 1
    assert (install_dir / "Planning.exe").read_bytes() == b"old-exe"
    notice = tmp_path / "localappdata" / "Planning" / "update_failed.txt"
    assert notice.is_file()
    assert "1.3.8" in notice.read_text(encoding="utf-8")


def test_update_preserves_user_data_and_sqlite_files(tmp_path, monkeypatch):
    install_dir = _make_complete_package(tmp_path / "current", marker_bytes=b"old-exe")
    data = install_dir / "settings"; data.mkdir()
    (data / "prefs.json").write_text("keep", encoding="utf-8")
    (install_dir / "planning.sqlite3").write_bytes(b"database")
    new_pkg = _make_complete_package(tmp_path / "new", marker_bytes=b"new-exe")
    zip_path = _zip_dir(new_pkg, tmp_path / "planning.zip")
    monkeypatch.setattr(updater_main, "launch_and_check", lambda exe, cwd, health, log: True)
    args = argparse.Namespace(zip=str(zip_path), install_dir=str(install_dir), backup_dir=str(tmp_path / "backup"),
                              version="1.3.8", parent_pid=0, log=str(tmp_path / "updater.log"), started_marker=None)
    assert updater_main.run(args) == 0
    assert (install_dir / "settings" / "prefs.json").read_text(encoding="utf-8") == "keep"
    assert (install_dir / "planning.sqlite3").read_bytes() == b"database"


def test_stale_health_marker_is_removed_before_new_launch(tmp_path, monkeypatch):
    health = tmp_path / "started.ok"
    health.write_text("stale", encoding="utf-8")
    class FakeProcess:
        pid = 123
        returncode = None
        def poll(self): return None
        def terminate(self): pass
    monkeypatch.setattr(updater_main.subprocess, "Popen", lambda *a, **kw: FakeProcess())
    monkeypatch.setattr(updater_main.time, "sleep", lambda _: None)
    assert not updater_main.launch_and_check(tmp_path / "Planning.exe", tmp_path, health, updater_main.logging.getLogger("test"))
    assert not health.exists()


def test_packaged_launch_clears_external_python_environment(tmp_path, monkeypatch):
    captured = {}
    class FakeProcess:
        pid = 1
        returncode = 0
        def poll(self): return self.returncode
    def fake_popen(args, **kwargs):
        captured.update(kwargs["env"])
        return FakeProcess()
    monkeypatch.setenv("PYTHONHOME", "C:/wrong-python")
    monkeypatch.setenv("PYTHONPATH", "C:/wrong-python-path")
    monkeypatch.setattr(updater_main.subprocess, "Popen", fake_popen)
    assert not updater_main.launch_and_check(tmp_path / "Planning.exe", tmp_path, tmp_path / "health.ok", updater_main.logging.getLogger("test"))
    assert "PYTHONHOME" not in captured
    assert "PYTHONPATH" not in captured
    assert captured["PYTHONNOUSERSITE"] == "1"


def test_rollback_failure_is_reported_in_failure_notice(tmp_path, monkeypatch):
    install_dir = _make_complete_package(tmp_path / "current", marker_bytes=b"old-exe")
    new_pkg = _make_complete_package(tmp_path / "new", marker_bytes=b"broken-exe")
    zip_path = _zip_dir(new_pkg, tmp_path / "planning.zip")
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path / "localappdata"))
    monkeypatch.setattr(updater_main, "launch_and_check", lambda exe, cwd, health, log: False)
    real_copy = updater_main.copy_package
    calls = {"n": 0}
    def fail_rollback(source, target):
        calls["n"] += 1
        if calls["n"] == 2: raise OSError("simulated rollback lock")
        return real_copy(source, target)
    monkeypatch.setattr(updater_main, "copy_package", fail_rollback)
    args = argparse.Namespace(zip=str(zip_path), install_dir=str(install_dir), backup_dir=str(tmp_path / "backup"),
                              version="1.3.8", parent_pid=0, log=str(tmp_path / "updater.log"), started_marker=None)
    assert updater_main.run(args) == 1
    note = tmp_path / "localappdata" / "Planning" / "update_failed.txt"
    assert "rollback failed" in note.read_text(encoding="utf-8")
