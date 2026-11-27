"""GitHub release discovery and handoff to the packaged PlanningUpdater.exe."""
from __future__ import annotations
from dataclasses import dataclass
import ctypes, json, os, shutil, subprocess, sys, tempfile, time, zipfile
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from utility.utils import APP_DATA_DIR

DEFAULT_APP_VERSION = "1.3.10"
GITHUB_REPOSITORY = "bibo-crypto/Planning"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
UPDATE_FAILURE_NOTICE = APP_DATA_DIR / "update_failed.txt"
HELPER_START_TIMEOUT_SECONDS = 25
HELPER_POLL_SECONDS = 0.2


def version_file_path() -> Path:
    if getattr(sys, "frozen", False):
        root = Path(sys.executable).resolve().parent
        for candidate in (root / "version.txt", root / "_internal" / "version.txt"):
            if candidate.is_file(): return candidate
        return root / "version.txt"
    return Path(__file__).resolve().parent.parent / "version.txt"


def get_installed_version() -> str:
    try:
        value = version_file_path().read_text(encoding="utf-8-sig").strip().lstrip("\ufeff")
        return value.lstrip("vV") if value else DEFAULT_APP_VERSION
    except OSError:
        return DEFAULT_APP_VERSION


def write_version_file(version: str, target: Path | None = None) -> Path:
    path = target or version_file_path(); path.parent.mkdir(parents=True, exist_ok=True)
    value = str(version).strip().lstrip("vV")
    temp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temp.write_text(value + "\n", encoding="ascii"); temp.replace(path)
    if path.read_text(encoding="ascii").strip() != value: raise RuntimeError(f"The version file could not be verified at {path}.")
    return path

APP_VERSION = get_installed_version()

@dataclass(frozen=True)
class ReleaseInfo:
    version: str; tag_name: str; title: str; notes: str; page_url: str; installer_url: str = ""; installer_name: str = ""


def _version_tuple(value: str) -> tuple[int, ...]:
    result = []
    for part in str(value or "").strip().lstrip("vV").split("."):
        digits = "".join(c for c in part if c.isdigit())
        if not digits: break
        result.append(int(digits))
    return tuple(result or [0])


def is_newer_version(candidate: str, current: str | None = None) -> bool:
    return _version_tuple(candidate) > _version_tuple(current or get_installed_version())


def _choose_installer(assets: list[dict]) -> tuple[str, str]:
    choices = [(str(a.get("name", "")), str(a.get("browser_download_url", ""))) for a in assets]
    choices = [(n, u) for n, u in choices if u and Path(n).suffix.lower() == ".zip"]
    choices.sort(key=lambda x: (not x[0].casefold().startswith("planning"), x[0].casefold()))
    return choices[0] if choices else ("", "")


def fetch_latest_release(timeout: float = 6.0) -> ReleaseInfo | None:
    request = Request(RELEASES_API_URL, headers={"Accept": "application/vnd.github+json", "User-Agent": "Planning-Updater"})
    try:
        with urlopen(request, timeout=timeout) as response: payload = json.loads(response.read().decode("utf-8"))
    except (HTTPError, URLError, TimeoutError, OSError, ValueError): return None
    tag = str(payload.get("tag_name", "")).strip(); version = tag.lstrip("vV")
    if not tag or not is_newer_version(version): return None
    name, url = _choose_installer(payload.get("assets") or [])
    return ReleaseInfo(version, tag, str(payload.get("name", "") or tag), str(payload.get("body", "") or "").strip(), str(payload.get("html_url", "") or RELEASES_PAGE_URL), url, name)


def check_for_updates_async(callback: Callable[[ReleaseInfo | None], None], logger=None) -> None:
    import threading
    def worker():
        try: callback(fetch_latest_release())
        except Exception:  # noqa: BLE001
            if logger: logger.exception("Update check failed")
    threading.Thread(target=worker, name="planning-update-check", daemon=True).start()


def download_installer(release: ReleaseInfo, progress: Callable[[int], None] | None = None) -> Path:
    if not release.installer_url: raise RuntimeError("This release has no complete Windows ZIP package attached.")
    fd, raw = tempfile.mkstemp(prefix="Planning_Update_", suffix=".zip"); os.close(fd); destination = Path(raw)
    try:
        request = Request(release.installer_url, headers={"User-Agent": "Planning-Updater"})
        with urlopen(request, timeout=60) as response, destination.open("wb") as output:
            total = int(response.headers.get("Content-Length", "0") or 0); downloaded = 0
            while chunk := response.read(1024 * 256):
                output.write(chunk); downloaded += len(chunk)
                if progress and total: progress(int(downloaded * 100 / total))
        if total and downloaded != total: raise RuntimeError(f"Download incomplete: got {downloaded} of {total} bytes.")
        try:
            archive = zipfile.ZipFile(destination)
        except zipfile.BadZipFile as exc:
            raise RuntimeError("The downloaded update ZIP is corrupt.") from exc
        with archive:
            if archive.testzip(): raise RuntimeError("The downloaded update ZIP is corrupt.")
            names = {n.replace("\\", "/").casefold() for n in archive.namelist()}
            basenames = {Path(n).name for n in names}
            if ("planning.exe" not in basenames
                    or not any(Path(n).name.startswith("python3") and n.endswith(".dll") for n in names)
                    or not any(Path(n).name == "base_library.zip" for n in names)):
                raise RuntimeError("The downloaded update is incomplete; upload the whole package made by build.bat zip.")
    except Exception:
        destination.unlink(missing_ok=True); raise
    return destination


def _needs_elevation(install_dir: Path) -> bool:
    probe = install_dir / f".planning_write_test_{os.getpid()}.tmp"
    try: probe.write_text("x", encoding="ascii"); probe.unlink(missing_ok=True); return False
    except OSError: return True

@dataclass(frozen=True)
class UpdateLaunch:
    started_marker: Path; stage_root: Path; updater_path: Path; elevated: bool; timeout: float = 25.0; cancel_marker: Path | None = None
    @property
    def script_path(self) -> Path:
        """Compatibility name used by older diagnostics; this is now an EXE path."""
        return self.updater_path
    def wait_until_started(self, pump: Callable[[], None] | None = None, *, timeout: float | None = None, sleep=time.sleep, clock=time.monotonic) -> bool:
        deadline = clock() + (self.timeout if timeout is None else timeout)
        while clock() < deadline:
            if self.started_marker.exists(): return True
            if pump: pump()
            sleep(0.2)
        return self.started_marker.exists()
    def cancel(self) -> None:
        if self.cancel_marker:
            self.cancel_marker.write_text("cancelled\n", encoding="utf-8")


def _start_updater(path: Path, args: list[str], elevated: bool) -> None:
    if not elevated:
        subprocess.Popen([str(path), *args], creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), close_fds=True); return
    if sys.platform != "win32": raise RuntimeError("Administrator approval is required for this installation.")
    params = " ".join('"' + a.replace('"', '\\"') + '"' for a in args)
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", str(path), params, str(path.parent), 1)
    if result <= 32: raise RuntimeError("Windows administrator approval was not granted; nothing was changed.")


def helper_not_started_message(launch: UpdateLaunch) -> str:
    return ("The update could not be started, so nothing was changed and Planning stays open.\n\n"
            f"Windows security or an antivirus product may have blocked {launch.updater_path}.\n"
            "Check Windows Security protection history and the Planning updater log; do not disable protection.")


def install_update(zip_path: Path, install_dir: Path, new_version: str) -> UpdateLaunch:
    if not zip_path.is_file(): raise FileNotFoundError(zip_path)
    if not getattr(sys, "frozen", False): raise RuntimeError("Automatic updates are available only in the installed Windows version.")
    updater = install_dir / "PlanningUpdater.exe"
    if not updater.is_file(): raise RuntimeError(f"The installed updater is missing: {updater}")
    stage = Path(tempfile.mkdtemp(prefix="Planning_Update_")); marker = stage / "updater_started.ok"; cancel = stage / "updater_cancelled.ok"; elevated = _needs_elevation(install_dir)
    staged_updater = stage / "PlanningUpdater.exe"
    shutil.copy2(updater, staged_updater)
    backup = install_dir.parent / "Planning_Backup"
    args = ["--zip", str(zip_path), "--install-dir", str(install_dir), "--backup-dir", str(backup), "--version", new_version, "--parent-pid", str(os.getpid()), "--started-marker", str(marker)]
    try: _start_updater(staged_updater, args, elevated)
    except Exception:
        shutil.rmtree(stage, ignore_errors=True); zip_path.unlink(missing_ok=True); raise
    return UpdateLaunch(marker, stage, staged_updater, elevated, cancel_marker=cancel)


def _safe_extract(zip_path: Path, destination: Path) -> None:
    """Compatibility wrapper for package-path tests; extraction is owned by the EXE."""
    destination.mkdir(parents=True, exist_ok=True)
    root = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != root and root not in target.parents:
                raise RuntimeError("The update ZIP contains an unsafe file path.")
        archive.extractall(destination)


def consume_update_failure_notice(path: Path | None = None) -> str | None:
    note = Path(path) if path else UPDATE_FAILURE_NOTICE
    try: raw = note.read_text(encoding="utf-8-sig")
    except OSError: return None
    note.unlink(missing_ok=True); fields = dict(line.split("=", 1) for line in raw.splitlines() if "=" in line)
    message = f"The update to {fields.get('version', 'the new version')} was NOT installed. The previous version is still in use and nothing was lost.\n\nReason: {fields.get('reason', 'unknown')}"
    if fields.get("log"): message += f"\n\nDetails: {fields['log']}"
    return message
