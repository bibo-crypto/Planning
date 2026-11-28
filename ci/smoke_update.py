r"""Run the real built PlanningUpdater.exe against a disposable installation.

This is intentionally an end-to-end Windows test: it creates a release ZIP from
an actual dist\Planning folder, starts the actual updater executable, lets it
replace an actual install directory, and verifies the startup health check and
preserved user data. No real user profile is touched.
"""
from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path


def zip_contents(source: Path, target: Path) -> None:
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(source.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(source).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--updater", required=True, type=Path)
    parser.add_argument("--package-root", required=True, type=Path)
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()

    root = args.data_root.resolve()
    install = root / "install"
    backup = root / "backup"
    profile = root / "profile"
    package = root / "package"
    archive = root / "update.zip"
    marker = root / "updater_started.ok"
    log = root / "updater.log"
    root.mkdir(parents=True, exist_ok=True)
    shutil.copytree(args.package_root, package)
    shutil.copytree(args.package_root, install)
    (install / "settings").mkdir()
    (install / "settings" / "keep.json").write_text('{"keep": true}\n', encoding="utf-8")
    (install / "planning.sqlite3").write_bytes(b"existing sqlite bytes")
    zip_contents(package, archive)

    for name in ("LOCALAPPDATA", "PLANNING_DATA_DIR", "USERPROFILE", "HOME"):
        (profile / name).mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.update({
        "LOCALAPPDATA": str(profile / "LOCALAPPDATA"),
        "PLANNING_DATA_DIR": str(profile / "PLANNING_DATA_DIR"),
        "USERPROFILE": str(profile / "USERPROFILE"),
        "HOME": str(profile / "HOME"),
        # Deliberately hostile values: the updater and the frozen app must ignore them.
        "PYTHONHOME": str(root / "not-python"),
        "PYTHONPATH": str(root / "not-python-path"),
        "PYTHONPLATLIBDIR": "not-a-platform-dir",
    })
    command = [
        str(args.updater.resolve()), "--zip", str(archive),
        "--install-dir", str(install), "--backup-dir", str(backup),
        "--version", "windows-smoke", "--parent-pid", "0",
        "--started-marker", str(marker), "--log", str(log),
    ]
    process = subprocess.Popen(command, cwd=install, env=environment)
    deadline = time.time() + args.timeout
    while time.time() < deadline and process.poll() is None:
        time.sleep(1)
    if process.poll() is None:
        process.kill()
        process.wait()
        print("FAILED: updater timed out")
        return 1
    if process.returncode != 0:
        print(f"FAILED: updater exited with code {process.returncode}")
        if log.exists(): print(log.read_text(encoding="utf-8", errors="replace"))
        return 1
    if not marker.is_file():
        print("FAILED: updater did not write its startup marker")
        return 1
    if (install / "version.txt").read_text(encoding="ascii").strip() != "windows-smoke":
        print("FAILED: version.txt was not updated")
        return 1
    if (install / "settings" / "keep.json").read_text(encoding="utf-8") != '{"keep": true}\n':
        print("FAILED: settings data was not preserved")
        return 1
    if (install / "planning.sqlite3").read_bytes() != b"existing sqlite bytes":
        print("FAILED: SQLite data was not preserved")
        return 1
    print("WINDOWS UPDATE SMOKE OK: real updater replaced the package, passed startup health, and preserved data.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
