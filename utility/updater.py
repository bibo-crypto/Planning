"""GitHub Releases version checking and installer update helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from utility.utils import APP_DATA_DIR, logger as _app_logger

DEFAULT_APP_VERSION = "1.3.11"
GITHUB_REPOSITORY = "bibo-crypto/Planning"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
UPDATE_FAILURE_NOTICE = APP_DATA_DIR / "update_failed.txt"


def version_file_path() -> Path:
    """Return the installed version file, supporting PyInstaller's _internal layout."""
    if getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).resolve().parent
        for candidate in (install_dir / "version.txt", install_dir / "_internal" / "version.txt"):
            if candidate.is_file():
                return candidate
        return install_dir / "version.txt"
    return Path(__file__).resolve().parent.parent / "version.txt"


def get_installed_version() -> str:
    try:
        value = version_file_path().read_text(encoding="utf-8-sig").strip().lstrip("\ufeff")
        if value:
            return value.lstrip("vV")
    except OSError:
        pass
    return DEFAULT_APP_VERSION


def write_version_file(version: str, target: Path | None = None) -> Path:
    """Atomically write the installed version and return the written path."""
    path = target or version_file_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    normalized = str(version).strip().lstrip("vV")
    temporary.write_bytes((normalized + "\n").encode("utf-8"))
    temporary.replace(path)
    written = path.read_text(encoding="utf-8-sig").strip().lstrip("vV")
    if written != normalized:
        raise RuntimeError(f"The version file could not be verified at {path}.")
    return path


APP_VERSION = get_installed_version()


@dataclass(frozen=True)
class ReleaseInfo:
    version: str
    tag_name: str
    title: str
    notes: str
    page_url: str
    installer_url: str = ""
    installer_name: str = ""


def _version_tuple(value: str) -> tuple[int, ...]:
    """Parse v1.2.3-style versions; non-numeric suffixes are ignored."""
    clean = str(value or "").strip().lstrip("vV")
    parts: list[int] = []
    for part in clean.split("."):
        digits = "".join(ch for ch in part if ch.isdigit())
        if not digits:
            break
        parts.append(int(digits))
    return tuple(parts or [0])


def is_newer_version(candidate: str, current: str | None = None) -> bool:
    current = current or get_installed_version()
    return _version_tuple(candidate) > _version_tuple(current)


def _choose_installer(assets: list[dict]) -> tuple[str, str]:
    candidates = []
    for asset in assets:
        name = str(asset.get("name", ""))
        url = str(asset.get("browser_download_url", ""))
        if url and Path(name).suffix.casefold() == ".exe" and name.casefold().startswith("planning_setup"):
            candidates.append((name, url))
    candidates.sort(key=lambda item: item[0].casefold())
    return candidates[0] if candidates else ("", "")


def fetch_latest_release(timeout: float = 6.0) -> ReleaseInfo | None:
    """Fetch the latest release only when it has a Planning Setup executable."""
    request = Request(
        RELEASES_API_URL,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "Planning-Updater"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError):
        return None

    tag_name = str(payload.get("tag_name", "")).strip()
    version = tag_name.lstrip("vV")
    if not tag_name or not is_newer_version(version, get_installed_version()):
        return None
    installer_name, installer_url = _choose_installer(payload.get("assets") or [])
    if not installer_url:
        return None
    return ReleaseInfo(
        version=version,
        tag_name=tag_name,
        title=str(payload.get("name", "") or tag_name),
        notes=str(payload.get("body", "") or "").strip(),
        page_url=str(payload.get("html_url", "") or RELEASES_PAGE_URL),
        installer_url=installer_url,
        installer_name=installer_name,
    )


def check_for_updates_async(callback: Callable[[ReleaseInfo | None], None], logger=None) -> None:
    """Check GitHub in a daemon thread and invoke *callback* when finished."""
    import threading

    def worker() -> None:
        try:
            callback(fetch_latest_release())
        except Exception:  # noqa: BLE001
            if logger:
                logger.exception("Update check failed")

    threading.Thread(target=worker, name="planning-update-check", daemon=True).start()


def download_installer(release: ReleaseInfo, progress: Callable[[int], None] | None = None) -> Path:
    """Download and validate the release's Windows Setup executable."""
    if not release.installer_url:
        raise RuntimeError("This release has no Planning Setup executable attached yet.")
    if (
        Path(release.installer_name).suffix.casefold() != ".exe"
        or not release.installer_name.casefold().startswith("planning_setup")
    ):
        raise RuntimeError("The release does not contain a Planning_Setup Windows installer.")

    fd, raw_path = tempfile.mkstemp(prefix="Planning_Setup_", suffix=".exe")
    os.close(fd)
    destination = Path(raw_path)
    request = Request(release.installer_url, headers={"User-Agent": "Planning-Updater"})
    try:
        with urlopen(request, timeout=30) as response, destination.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0") or 0)
            downloaded = 0
            while True:
                chunk = response.read(1024 * 256)
                if not chunk:
                    break
                output.write(chunk)
                downloaded += len(chunk)
                if progress and total:
                    progress(min(100, int(downloaded * 100 / total)))
        if total and downloaded != total:
            raise RuntimeError(
                f"Download incomplete: got {downloaded} of {total} bytes. Check your internet connection and try again."
            )
        if not _is_windows_executable(destination):
            raise RuntimeError("The downloaded Setup is not a valid Windows executable. Please try again.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _is_windows_executable(path: Path) -> bool:
    """Check the DOS and PE signatures before offering a downloaded file to Windows."""
    try:
        with path.open("rb") as executable:
            if executable.read(2) != b"MZ":
                return False
            executable.seek(0x3C)
            offset_bytes = executable.read(4)
            if len(offset_bytes) != 4:
                return False
            pe_offset = int.from_bytes(offset_bytes, "little")
            executable.seek(pe_offset)
            return executable.read(4) == b"PE\0\0"
    except OSError:
        return False


def _needs_elevation(install_dir: Path) -> bool:
    """Probe whether the current user can write to the installed application directory."""
    probe = install_dir / f".planning_write_test_{os.getpid()}.tmp"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return False
    except OSError:
        return True


def launch_installer(installer_path: Path, install_dir: Path) -> None:
    """Open the downloaded Inno Setup installer, requesting UAC only for protected installs."""
    if not installer_path.is_file() or not _is_windows_executable(installer_path):
        raise RuntimeError("The Planning Setup file is missing or is not a valid Windows executable.")
    if os.name != "nt":
        raise RuntimeError("In-app installation is available only on Windows.")

    if _needs_elevation(install_dir):
        import ctypes

        result = ctypes.windll.shell32.ShellExecuteW(
            None, "runas", str(installer_path), None, str(installer_path.parent), 1
        )
        if result <= 32:
            raise RuntimeError(
                "Windows did not approve the installer. Approve the Administrator prompt and try again."
            )
        return

    subprocess.Popen([str(installer_path)], cwd=str(installer_path.parent), close_fds=True)


def consume_update_failure_notice(path: Path | None = None) -> str | None:
    """Show and remove a failure notice left by an older updater version."""
    note = Path(path) if path else UPDATE_FAILURE_NOTICE
    try:
        raw = note.read_text(encoding="utf-8-sig")
    except OSError:
        return None
    try:
        note.unlink()
    except OSError:
        pass
    fields = {}
    for line in raw.splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            fields[key.strip()] = value.strip()
    version = fields.get("version") or "the new version"
    message = (
        f"The update to {version} was NOT installed. The previous version ({get_installed_version()}) is still in use "
        f"and nothing was lost.\n\nReason: {fields.get('reason') or 'unknown'}"
    )
    if fields.get("log"):
        message += f"\n\nDetails: {fields['log']}"
    return message
