"""Smoke test for the packaged application: it must leave the loading screen, survive a restart and close.

    python ci/smoke_exe.py --exe dist\\Planning\\Planning.exe --data-root <empty temp folder>

The program is started with a throw-away profile (LOCALAPPDATA / PLANNING_DATA_DIR / HOME point into
*--data-root*), so it never touches a real user's data.  Run 1 starts on an empty profile and must log
"Planning started" (written only after every page was built).  Run 2 starts on the profile run 1 left
behind (database, settings, caches) and must do the same -- a restart on existing data is exactly where
"stuck on Loading application pages" shows up.  Exit code 0 = verified, 1 = failed (the logs are printed).
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

STARTED = "Planning started: all pages built"
BAD_MARKERS = ("Traceback", "could not build its pages", "No module named", "ImportError")


def _env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env["LOCALAPPDATA"] = str(root / "LocalAppData")          # the frozen EXE keeps its data here
    env["PLANNING_DATA_DIR"] = str(root / "PlanningData")     # ... a source run honours this instead
    env["USERPROFILE"] = env["HOME"] = str(root / "Home")
    for name in ("LocalAppData", "PlanningData", "Home"):
        (root / name).mkdir(parents=True, exist_ok=True)
    return env


def _log_files(root: Path) -> list[Path]:
    found = list((root / "LocalAppData").rglob("*.log")) + list((root / "PlanningData").rglob("*.log"))
    return sorted(set(found))


def _read_logs(root: Path) -> str:
    chunks = []
    for path in _log_files(root):
        chunks.append(f"----- {path} -----\n{path.read_text(encoding='utf-8', errors='replace')}")
    return "\n".join(chunks)


def _stop(process: subprocess.Popen, grace: float = 15.0) -> str:
    """Ask the program to close like a user would; kill it only if it ignores that."""
    if process.poll() is not None:
        return "exited_by_itself"
    if sys.platform == "win32":
        subprocess.run(["taskkill", "/PID", str(process.pid), "/T"], capture_output=True)   # WM_CLOSE
    else:
        process.terminate()
    try:
        process.wait(timeout=grace)
        return "closed"
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=10)
        return "killed_after_ignoring_close"


def run_once(command: list[str], root: Path, label: str, timeout: float) -> list[str]:
    problems: list[str] = []
    before = len(_read_logs(root))
    process = subprocess.Popen(command, env=_env(root), stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    deadline = time.time() + timeout
    started = False
    while time.time() < deadline:
        if STARTED in _read_logs(root)[before:]:
            started = True
            break
        if process.poll() is not None:
            problems.append(f"{label}: the program exited with code {process.returncode} before it finished starting")
            break
        time.sleep(0.5)
    else:
        problems.append(f"{label}: still on the loading screen after {timeout:.0f}s")
    time.sleep(1.0 if started else 0)
    outcome = _stop(process)
    print(f"{label}: started={started} stop={outcome}")
    if started and outcome == "exited_by_itself":
        problems.append(f"{label}: the program quit by itself right after starting")
    new_log = _read_logs(root)[before:]
    problems += [f"{label}: log contains {marker!r}" for marker in BAD_MARKERS if marker in new_log]
    for path in list(root.rglob("startup_hang.log")):            # the program's own "I was stuck here" evidence
        problems.append(f"{label}: {path.name} exists, the start did not finish: {path.read_text(encoding='utf-8', errors='replace')[:1500]}")
    for path in list((root / "LocalAppData").rglob("startup_error.log")):
        problems.append(f"{label}: {path.name} was written: {path.read_text(encoding='utf-8', errors='replace')[:500]}")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--exe", help="packaged Planning.exe")
    parser.add_argument("--source", help="run `python main.py` from this folder instead (for a dry run)")
    parser.add_argument("--data-root", required=True, type=Path)
    parser.add_argument("--timeout", type=float, default=120.0)
    args = parser.parse_args()
    if bool(args.exe) == bool(args.source):
        parser.error("give exactly one of --exe / --source")
    command = [args.exe] if args.exe else [sys.executable, str(Path(args.source) / "main.py")]
    if args.exe and not Path(args.exe).is_file():
        print(f"FAILED: {args.exe} does not exist")
        return 1
    problems = run_once(command, args.data_root, "run 1 (empty profile)", args.timeout)
    problems += run_once(command, args.data_root, "run 2 (restart on the saved profile)", args.timeout)
    if problems:
        print("\nSMOKE TEST FAILED")
        print("\n".join(f" - {p}" for p in problems))
        print("\n" + _read_logs(args.data_root))
        return 1
    print("SMOKE TEST OK: the program starts, leaves the loading screen, restarts on its own data and closes.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
