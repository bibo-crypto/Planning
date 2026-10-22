"""sync_venv_packages.py -- keep the build venv in step with requirements.txt.

build.bat runs this with the venv's own Python:

    venv\\Scripts\\python.exe sync_venv_packages.py --sync

``--sync`` edits the existing venv in place and touches the network only when it
has to:

  * requirements.txt unchanged since the last successful sync, and every package
    it lists is installed  ->  nothing is downloaded or installed at all;
  * otherwise  ->  packages no longer listed are removed, ``pip install -r
    requirements.txt`` adds the new/changed ones (pip itself skips everything
    already at the right version), and the new fingerprint is stored in the venv.

Without ``--sync`` only the removal step runs (the original behaviour).
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from importlib import metadata
from pathlib import Path

# Written inside the venv after a successful sync; holds the fingerprint of the
# requirements it was synced with.
STAMP_NAME = ".planning-requirements-stamp"

# Never remove these even if requirements.txt doesn't list them --
# pip/setuptools/wheel are the venv's own bootstrap tooling, not an
# app dependency, and PyInstaller is invoked by build.bat itself
# separately from requirements.txt.
ALWAYS_KEEP = {"pip", "setuptools", "wheel"}


def _normalize(name: str) -> str:
    """PEP 503 style: case-insensitive, '-'/'_'/'.' treated the same."""
    return re.sub(r"[-_.]+", "-", name.strip().lower())


def _requirement_names(requirements_path: Path) -> set[str]:
    names = set()
    if not requirements_path.is_file():
        return names
    for line in requirements_path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")):
            continue
        # Package name is everything before the first version/extra marker.
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if match:
            names.add(_normalize(match.group(1)))
    return names


def _with_dependencies(names: set[str]) -> set[str]:
    """*names* plus everything they (transitively) need at run time.

    `pip list` shows transitive packages too (pdfminer.six, Pillow, pluggy ...),
    and they are not written in requirements.txt -- without this closure the
    prune step would uninstall them (and pytest's own helpers with it).
    """
    from importlib import metadata

    seen: set[str] = set()
    pending = list(names)
    while pending:
        name = _normalize(pending.pop())
        if name in seen:
            continue
        seen.add(name)
        try:
            requires = metadata.distribution(name).requires or []
        except metadata.PackageNotFoundError:
            continue
        for requirement in requires:
            if "extra ==" in requirement.replace("'", '"') or "extra==" in requirement.replace(" ", ""):
                continue            # optional extras are not installed by default
            match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", requirement.strip())
            if match:
                pending.append(match.group(1))
    return seen


def _installed_names() -> set[str]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "list", "--format=freeze"],
        capture_output=True, text=True, check=True,
    )
    names = set()
    for line in result.stdout.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "==" not in line:
            continue
        names.add(_normalize(line.split("==", 1)[0]))
    return names


def requirements_fingerprint(root: Path) -> str:
    """Fingerprint of what the venv must contain: the text of requirements.txt
    (comments and blank lines ignored, so editing a comment changes nothing) plus
    the Python major.minor the venv runs on."""
    path = root / "requirements.txt"
    lines = []
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.split("#", 1)[0].strip()
            if line:
                lines.append(line)
    payload = "\n".join(lines) + f"\npython={sys.version_info[0]}.{sys.version_info[1]}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _applies_here(requirement_line: str) -> bool:
    """False for a requirement whose environment marker excludes this machine
    (e.g. ``pywin32; sys_platform == "win32"`` on Linux)."""
    if ";" not in requirement_line:
        return True
    marker_text = requirement_line.split(";", 1)[1].strip()
    try:
        try:
            from packaging.markers import Marker
        except ImportError:                       # packaging not installed: use pip's copy
            from pip._vendor.packaging.markers import Marker
        return bool(Marker(marker_text).evaluate())
    except Exception:
        return True                               # cannot tell -> assume it is needed


def missing_requirements(root: Path) -> list[str]:
    """Names listed in requirements.txt (for this machine) that are not installed."""
    path = root / "requirements.txt"
    missing = []
    if not path.is_file():
        return missing
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith(("-", "git+", "http://", "https://")) or not _applies_here(line):
            continue
        match = re.match(r"^([A-Za-z0-9][A-Za-z0-9._-]*)", line)
        if not match:
            continue
        try:
            metadata.version(match.group(1))
        except metadata.PackageNotFoundError:
            missing.append(match.group(1))
    return missing


def is_environment_current(root: Path, stamp_path: Path) -> bool:
    """True when the venv was already synced with this exact requirements.txt and
    nothing it lists has since gone missing -- then no pip run is needed."""
    try:
        stored = stamp_path.read_text(encoding="utf-8").strip()
    except OSError:
        return False
    return stored == requirements_fingerprint(root) and not missing_requirements(root)


def _pip_install(requirements_path: Path) -> int:
    """``pip install -r`` into this interpreter's environment; returns pip's exit code.
    pip downloads only what is missing or no longer satisfies a pin."""
    return subprocess.run(
        [sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--quiet",
         "-r", str(requirements_path)],
    ).returncode


def sync(root: Path | None = None, stamp_path: Path | None = None) -> int:
    """Bring the venv in line with requirements.txt, doing as little as possible.
    Returns 0 on success, otherwise pip's non-zero exit code."""
    root = root or Path(__file__).resolve().parent
    stamp_path = stamp_path or Path(sys.prefix) / STAMP_NAME
    if is_environment_current(root, stamp_path):
        print("[sync_venv] venv is up to date -- nothing to download or install.")
        return 0
    still_missing = missing_requirements(root)
    if still_missing:
        print("[sync_venv] Installing missing package(s): " + ", ".join(still_missing))
    elif not stamp_path.exists():
        print("[sync_venv] First sync of this venv -- pip downloads only what is not installed yet.")
    else:
        print("[sync_venv] requirements.txt changed -- updating the existing venv in place.")
    main()                                       # remove packages that are no longer listed
    code = _pip_install(root / "requirements.txt")
    if code != 0:
        print("[sync_venv] pip install failed; the venv was NOT marked up to date.")
        return code
    stamp_path.write_text(requirements_fingerprint(root), encoding="utf-8")
    print("[sync_venv] venv is up to date.")
    return 0


def main() -> int:
    """Remove from the virtual environment every package that is not (directly or as a dependency) in requirements.txt / requirements-dev.txt.
    Returns 0 on success.
    """
    root = Path(__file__).resolve().parent
    # requirements-dev.txt (pytest, pyflakes) is kept too: pruning must not
    # remove the tools the tests need.  It pulls requirements.txt in via -r.
    wanted = _requirement_names(root / "requirements.txt") | _requirement_names(root / "requirements-dev.txt")
    wanted = _with_dependencies(wanted) | {_normalize(p) for p in ALWAYS_KEEP}
    installed = _installed_names()
    to_remove = sorted(installed - wanted)

    if not to_remove:
        print("[sync_venv] Nothing to remove -- venv already matches requirements.txt.")
        return 0

    print(f"[sync_venv] Removing {len(to_remove)} package(s) no longer in requirements.txt:")
    for name in to_remove:
        print(f"  - {name}")

    subprocess.run(
        [sys.executable, "-m", "pip", "uninstall", "-y", "--quiet", *to_remove],
        check=False,  # a single stubborn package shouldn't abort the whole build
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(sync() if "--sync" in sys.argv[1:] else main())
