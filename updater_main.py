"""PlanningUpdater.exe entry point.

This is a small, visible application component rather than a generated script.  It
runs only after Planning has exited, validates the complete package, preserves a
verified backup, replaces application files, verifies startup through an explicit
health marker, and restores the previous version on failure.
"""
from __future__ import annotations

import argparse
import ctypes
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import time
import zipfile


def log_path(value: str | None) -> Path:
    if value:
        return Path(value)
    return Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Planning" / "logs" / "updater.log"


def configure_logging(path: Path) -> logging.Logger:
    path.parent.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("PlanningUpdater")
    logger.setLevel(logging.DEBUG)
    handler = logging.FileHandler(path, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    logger.addHandler(handler)
    return logger


def wait_for_parent(pid: int, logger: logging.Logger) -> None:
    if not pid:
        return
    for attempt in range(90):
        try:
            handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
            if not handle:
                logger.info("Parent process %s has exited (attempt %s)", pid, attempt + 1)
                return
            ctypes.windll.kernel32.CloseHandle(handle)
        except (AttributeError, OSError):
            # Non-Windows test environments do not expose the Windows API.
            return
        time.sleep(1)
    logger.warning("Parent process %s did not exit within the wait period", pid)
    # Give the OS a moment to release file locks even after the process exits.
    time.sleep(2)


def safe_extract(source: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source) as archive:
        members = archive.infolist()
        root = destination.resolve()
        for member in members:
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError(f"unsafe ZIP member path: {member.filename}")
        archive.extractall(destination)
    executables = sorted(destination.rglob("Planning.exe"), key=lambda p: len(p.parts))
    if not executables:
        raise RuntimeError("The update package does not contain Planning.exe.")
    app_root = executables[0].parent
    internal = app_root / "_internal"
    if not any(internal.glob("python3*.dll")):
        raise RuntimeError("The update package is incomplete: _internal\\python3*.dll is missing.")
    if not any(internal.glob("base_library.zip")):
        raise RuntimeError("The update package is incomplete: _internal\\base_library.zip is missing.")
    return app_root


def snapshot(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination)
    source_files = sorted(p.relative_to(source) for p in source.rglob("*") if p.is_file())
    backup_files = sorted(p.relative_to(destination) for p in destination.rglob("*") if p.is_file())
    if source_files != backup_files:
        raise RuntimeError("The backup could not be verified; no installed files were changed.")
    for relative in source_files:
        if (source / relative).read_bytes() != (destination / relative).read_bytes():
            raise RuntimeError(f"The backup failed verification for {relative}")


def copy_package(source: Path, target: Path) -> None:
    for item in source.iterdir():
        destination = target / item.name
        if item.is_dir():
            _copy_tree_with_retry(item, destination)
        else:
            _copy_file_with_retry(item, destination)


def _copy_file_with_retry(src: Path, dst: Path, retries: int = 5, delay: float = 2.0) -> None:
    """Copy a single file, retrying on PermissionError (locked by antivirus or OS)."""
    for attempt in range(retries):
        try:
            shutil.copy2(src, dst)
            return
        except PermissionError:
            # Windows locks a running .exe against overwrite, but allows renaming it.
            if dst.exists() and dst.suffix.lower() == ".exe":
                old = dst.with_name(f"{dst.name}.{os.getpid()}.old")
                try:
                    old.unlink(missing_ok=True)
                    dst.rename(old)
                    shutil.copy2(src, dst)
                    return
                except OSError:
                    pass
            if attempt == retries - 1:
                raise
            time.sleep(delay)


def _copy_tree_with_retry(src: Path, dst: Path) -> None:
    """Copy a directory tree, retrying individual files on PermissionError."""
    dst.mkdir(parents=True, exist_ok=True)
    for item in src.iterdir():
        destination = dst / item.name
        if item.is_dir():
            _copy_tree_with_retry(item, destination)
        else:
            _copy_file_with_retry(item, destination)


def write_version(target: Path, version: str) -> None:
    temporary = target / f".version.{os.getpid()}.tmp"
    temporary.write_text(version.lstrip("vV").strip() + "\n", encoding="ascii", newline="\n")
    temporary.replace(target / "version.txt")
    actual = (target / "version.txt").read_text(encoding="ascii").strip()
    if actual != version.lstrip("vV").strip():
        raise RuntimeError("version.txt verification failed")


def launch_and_check(exe: Path, working_dir: Path, health_file: Path, logger: logging.Logger) -> bool:
    health_file.unlink(missing_ok=True)
    environment = os.environ.copy()
    # A user's system Python variables can point the embedded interpreter at a
    # different stdlib and produce "Failed to import encodings module".
    # PyInstaller supplies its own interpreter and must not inherit them.
    for name in ("PYTHONHOME", "PYTHONPATH", "PYTHONPLATLIBDIR"):
        environment.pop(name, None)
    environment["PYTHONNOUSERSITE"] = "1"
    environment["PLANNING_UPDATE_HEALTH_FILE"] = str(health_file)
    process = subprocess.Popen([str(exe)], cwd=working_dir, env=environment, close_fds=True)
    logger.info("Started %s as PID %s; waiting for health marker %s", exe, process.pid, health_file)
    for _ in range(60):
        if health_file.is_file():
            return True
        if process.poll() is not None:
            logger.error("Planning exited before health check, code %s", process.returncode)
            return False
        time.sleep(1)
    logger.error("Planning did not create the startup health marker")
    try:
        process.terminate()
    except OSError:
        pass
    return False


def run(args: argparse.Namespace) -> int:
    logger = configure_logging(log_path(args.log))
    if args.started_marker:
        Path(args.started_marker).write_text("PlanningUpdater started\n", encoding="utf-8")
    target = Path(args.install_dir).resolve()
    backup = Path(args.backup_dir).resolve()
    stage = Path(tempfile.mkdtemp(prefix="PlanningUpdater_"))
    health = stage / "planning_started.ok"
    try:
        wait_for_parent(args.parent_pid, logger)
        source = safe_extract(Path(args.zip), stage / "package")
        logger.info("Validated update package %s from %s", args.version, source)
        snapshot(target, backup)
        copy_package(source, target)
        write_version(target, args.version)
        if not launch_and_check(target / "Planning.exe", target, health, logger):
            raise RuntimeError("The new version did not pass its startup health check")
        logger.info("Update to %s completed successfully", args.version)
        Path(args.zip).unlink(missing_ok=True)
        shutil.rmtree(stage, ignore_errors=True)
        return 0
    except Exception as exc:  # noqa: BLE001
        logger.exception("Update failed: %s", exc)
        rollback_error = None
        try:
            if backup.is_dir():
                if target.exists():
                    for old in target.glob("*.old"):
                        try:
                            old.unlink()
                        except OSError:
                            pass
                copy_package(backup, target)
                logger.info("Restored the verified backup")
                launch_and_check(target / "Planning.exe", target, health, logger)
        except Exception as rollback_exc:
            rollback_error = rollback_exc
            logger.exception("Rollback failed")
        notice = Path(os.environ.get("LOCALAPPDATA") or Path.home()) / "Planning" / "update_failed.txt"
        notice.parent.mkdir(parents=True, exist_ok=True)
        reason = str(exc)
        if rollback_error is not None:
            reason += f"; rollback failed: {rollback_error}"
        notice.write_text(f"version={args.version}\nreason={reason}\nlog={log_path(args.log)}\n", encoding="utf-8")
        return 1
    finally:
        shutil.rmtree(stage, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Planning application updater")
    parser.add_argument("--zip", required=True)
    parser.add_argument("--install-dir", required=True)
    parser.add_argument("--backup-dir", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--parent-pid", type=int, default=0)
    parser.add_argument("--log")
    parser.add_argument("--started-marker")
    return run(parser.parse_args())


if __name__ == "__main__":
    raise SystemExit(main())
