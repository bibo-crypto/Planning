"""Regression tests for the transparent PlanningUpdater.exe protocol."""
from __future__ import annotations
import sys, zipfile
from pathlib import Path

import pytest
from utility import updater
import updater_main
from updater_main import safe_extract, snapshot, write_version


def _launch(tmp_path, elevated=False):
    stage = tmp_path / "stage"
    stage.mkdir(exist_ok=True)
    return updater.UpdateLaunch(
        stage / "started.ok", stage, tmp_path / "PlanningUpdater.exe", elevated,
        timeout=0.4, cancel_marker=stage / "cancel.ok",
    )


def make_package(root: Path) -> Path:
    package = root / "Planning"
    (package / "_internal").mkdir(parents=True)
    (package / "Planning.exe").write_bytes(b"new executable")
    (package / "PlanningUpdater.exe").write_bytes(b"updater")
    (package / "_internal" / "python312.dll").write_bytes(b"python")
    (package / "_internal" / "base_library.zip").write_bytes(b"python-stdlib")
    return package


def zip_package(package: Path, target: Path) -> Path:
    with zipfile.ZipFile(target, "w") as archive:
        for path in package.rglob("*"):
            if path.is_file(): archive.write(path, path.relative_to(package).as_posix())
    return target


def test_download_selection_prefers_the_complete_planning_zip():
    assert updater._choose_installer([
        {"name": "notes.zip", "browser_download_url": "n"},
        {"name": "Planning_v2.0.0.zip", "browser_download_url": "p"},
    ]) == ("Planning_v2.0.0.zip", "p")


def test_package_validation_accepts_nested_whole_program(tmp_path):
    archive = zip_package(make_package(tmp_path), tmp_path / "release.zip")
    extracted = safe_extract(archive, tmp_path / "stage")
    assert extracted.name == "stage"
    assert (extracted / "Planning.exe").is_file()


def test_package_validation_rejects_path_traversal(tmp_path):
    archive = tmp_path / "unsafe.zip"
    with zipfile.ZipFile(archive, "w") as z: z.writestr("../escape.txt", "bad")
    with pytest.raises(RuntimeError, match="unsafe"):
        safe_extract(archive, tmp_path / "stage")


def test_backup_is_byte_for_byte_verified(tmp_path):
    source = make_package(tmp_path / "source")
    backup = tmp_path / "backup"
    snapshot(source, backup)
    assert {p.relative_to(source): p.read_bytes() for p in source.rglob("*") if p.is_file()} == {p.relative_to(backup): p.read_bytes() for p in backup.rglob("*") if p.is_file()}


def test_version_write_is_plain_and_verified(tmp_path):
    target = tmp_path / "install"; target.mkdir()
    write_version(target, "v2.4.6")
    assert (target / "version.txt").read_bytes() == b"2.4.6\n"


def test_launch_waits_for_explicit_marker(tmp_path):
    marker = tmp_path / "started.ok"
    launch = updater.UpdateLaunch(marker, tmp_path, tmp_path / "PlanningUpdater.exe", False, timeout=1)
    sleeps = []
    def sleep(seconds):
        sleeps.append(seconds)
        marker.write_text("started")
    assert launch.wait_until_started(sleep=sleep, clock=lambda: 0.0)
    assert sleeps


def test_missing_updater_is_reported_before_any_change(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    install = tmp_path / "install"; install.mkdir()
    archive = tmp_path / "update.zip"; archive.write_bytes(b"zip")
    with pytest.raises(RuntimeError, match="updater is missing"):
        updater.install_update(archive, install, "2.0.0")
    assert archive.exists()


def test_updater_launch_failure_cleans_staging_and_download(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    install = tmp_path / "install"; install.mkdir()
    (install / "PlanningUpdater.exe").write_bytes(b"updater")
    archive = tmp_path / "update.zip"; archive.write_bytes(b"zip")
    def reject(*args, **kwargs): raise OSError("blocked by security software")
    monkeypatch.setattr(updater, "_start_updater", reject)
    with pytest.raises(OSError, match="blocked"):
        updater.install_update(archive, install, "2.0.0")
    assert not archive.exists()
    assert not list(tmp_path.glob("Planning_Update_*"))


def test_uac_rejection_is_reported_without_running_update(monkeypatch, tmp_path):
    monkeypatch.setattr(updater.sys, "platform", "win32")
    class Shell32:
        @staticmethod
        def ShellExecuteW(*args): return 32
    class Windll: shell32 = Shell32()
    monkeypatch.setattr(updater.ctypes, "windll", Windll(), raising=False)
    with pytest.raises(RuntimeError, match="approval was not granted"):
        updater._start_updater(tmp_path / "PlanningUpdater.exe", ["--zip", "x"], True)


def test_parent_timeout_logs_warning(monkeypatch, tmp_path):
    events = []
    logger = __import__("logging").getLogger("parent-timeout")
    logger.warning = lambda *args, **kwargs: events.append(args)
    class Kernel:
        def OpenProcess(self, *args): return 1
        def CloseHandle(self, *args): pass
    class Windll: kernel32 = Kernel()
    monkeypatch.setattr(updater_main.ctypes, "windll", Windll(), raising=False)
    monkeypatch.setattr(updater_main.time, "sleep", lambda _: None)
    updater_main.wait_for_parent(123, logger)
    assert any("did not exit" in str(args[0]) for args in events)
