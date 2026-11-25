"""GitHub Releases version checking and installer update helpers."""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
import zipfile

from utility.utils import APP_DATA_DIR, logger as _app_logger

DEFAULT_APP_VERSION = "1.3.6"
GITHUB_REPOSITORY = "bibo-crypto/Planning"
RELEASES_API_URL = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
RELEASES_PAGE_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
# Written by the update helper when an update could not be installed; shown (once) on the next start.
UPDATE_FAILURE_NOTICE = APP_DATA_DIR / "update_failed.txt"


def version_file_path() -> Path:
    """Return the installed version file, supporting PyInstaller's _internal layout."""
    if getattr(sys, "frozen", False):
        install_dir = Path(sys.executable).resolve().parent
        # The external file is authoritative: the updater can replace it
        # without rebuilding the PyInstaller internal archive.
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
    temporary.write_text(str(version).strip().lstrip("vV") + "\n", encoding="utf-8")
    temporary.replace(path)
    written = path.read_text(encoding="utf-8-sig").strip().lstrip("vV")
    if written != str(version).strip().lstrip("vV"):
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
        if url and Path(name).suffix.lower() == ".zip":
            candidates.append((name, url))
    # ``build.bat`` creates Planning_v<version>.zip. Prefer it (or a plain Planning.zip) over unrelated ZIP attachments
    # (a log, a source archive); among equals the name decides, so the choice never depends on the order GitHub lists them.
    candidates.sort(key=lambda item: (not Path(item[0]).name.casefold().startswith("planning"), "setup" not in item[0].casefold(), item[0].casefold()))
    return candidates[0] if candidates else ("", "")


def fetch_latest_release(timeout: float = 6.0) -> ReleaseInfo | None:
    """Fetch the latest published GitHub release, returning None on failure."""
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
    """Download the release ZIP to a temporary file and return its path."""
    if not release.installer_url:
        raise RuntimeError("This release has no Windows installer attached yet.")
    suffix = ".zip"
    fd, raw_path = tempfile.mkstemp(prefix="Planning_Update_", suffix=suffix)
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
                    progress(int(downloaded * 100 / total))
        # A network hiccup mid-download can end the response early without
        # urlopen/read ever raising -- silently continuing with a truncated
        # or corrupt ZIP produced exactly this symptom in the wild: the
        # install script would extract *something*, but Windows refused to
        # run it ("not a valid application for this OS platform"), and that
        # only ever surfaced deep in the PowerShell log, long after this
        # function returned successfully. Catch it right here instead.
        if total and downloaded != total:
            raise RuntimeError(
                f"Download incomplete: got {downloaded} of {total} bytes. Check your internet connection and try again."
            )
        try:
            with zipfile.ZipFile(destination) as archive:
                bad_file = archive.testzip()
        except zipfile.BadZipFile as exc:
            raise RuntimeError("The downloaded update file is corrupt. Please try again.") from exc
        if bad_file:
            raise RuntimeError(f"The downloaded update file is corrupt (bad entry: {bad_file}). Please try again.")
    except Exception:
        destination.unlink(missing_ok=True)
        raise
    return destination


def _safe_extract(zip_path: Path, destination: Path) -> None:
    """Extract a ZIP without allowing members to escape the temp folder."""
    destination_resolved = destination.resolve()
    with zipfile.ZipFile(zip_path) as archive:
        for member in archive.infolist():
            target = (destination / member.filename).resolve()
            if target != destination_resolved and destination_resolved not in target.parents:
                raise RuntimeError("The update ZIP contains an unsafe file path.")
        archive.extractall(destination)


def _powershell_quote(value: Path | str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _needs_elevation(install_dir: Path) -> bool:
    """True if the current (non-admin) process cannot write into install_dir
    -- e.g. it's under C:\\Program Files, which every normal user account
    (including the one that owns/runs this installation) needs
    Administrator rights to modify. Probed with a real write, not a guess
    from the path alone, so a per-user install location (%LOCALAPPDATA%)
    never triggers an unnecessary UAC prompt."""
    probe = install_dir / f".planning_write_test_{os.getpid()}.tmp"
    try:
        probe.write_text("x", encoding="utf-8")
        probe.unlink(missing_ok=True)
        return False
    except OSError:
        return True


def _run_update_script(script_path: Path, creation_flags: int, elevated: bool) -> None:
    """Start the PowerShell update script.
    When elevated, it is started through the Windows UAC "runas" prompt because the install folder (Program Files) needs Administrator rights; otherwise it is started directly and hidden.
    """
    if not elevated:
        subprocess.Popen(
            ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-WindowStyle", "Hidden", "-File", str(script_path)],
            creationflags=creation_flags,
            close_fds=True,
        )
        return
    # install_dir (typically C:\Program Files\Planning) needs Administrator
    # rights to write to, same as any other app installed there -- this is
    # not optional, so request elevation via the UAC prompt (the "runas"
    # verb) rather than letting every Copy-Item in the script fail with
    # Access Denied, including the rollback's own copy-back, which used to
    # leave nothing running at all (see install_update's docstring).
    import ctypes
    args = f'-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "{script_path}"'
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe", args, None, 0)
    if result <= 32:  # ShellExecuteW's own convention: <=32 means it failed to even launch
        raise RuntimeError(
            "This update needs Administrator approval to install (Planning is installed under "
            "Program Files). Please approve the Windows prompt, or ask an admin to run the update."
        )


def consume_update_failure_notice(path: Path | None = None) -> str | None:
    """The message for the user when the last update was NOT installed, else None.

    The update helper leaves ``update_failed.txt`` when it had to roll back; it is removed here so the message appears once.
    """
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
    message = (f"The update to {version} was NOT installed. The previous version ({get_installed_version()}) is still in use "
               f"and nothing was lost.\n\nReason: {fields.get('reason') or 'unknown'}")
    if fields.get("log"):
        message += f"\n\nDetails: {fields['log']}"
    return message


def _check_package_is_complete(source_dir: Path) -> None:
    """Refuse a package that could not start, before anything of the installed version is touched.

    A PyInstaller build keeps the Python DLL in ``_internal``; an update ZIP without it (for example one holding only
    Planning.exe) would replace a working installation with one that stops at "Failed to load Python DLL ...".
    """
    exe = source_dir / "Planning.exe"
    if not exe.is_file() or exe.stat().st_size == 0:
        raise RuntimeError("The update ZIP must contain Planning.exe.")
    internal = source_dir / "_internal"
    if not internal.is_dir() or not any(internal.glob("python3*.dll")):
        raise RuntimeError(
            "The update package is incomplete (the Python DLL is missing from _internal), so it was not installed. "
            "The GitHub release must contain the WHOLE program folder: upload the ZIP made by \"build.bat zip\" "
            "(dist\\Planning_vX.zip), not Planning.exe alone."
        )


# The helper that replaces the files after the program has closed.  It is the script of the first working release (backup,
# copy, write version.txt, start, roll back) kept as small and plain as possible on purpose: antivirus products judge
# PowerShell scripts by what they contain, and a long script full of .NET calls, hashing and message boxes was removed as
# "Suspicious PowerShell script activity" (RAV Endpoint Protection, Risk.Powershell.Script.Gen.DIYST).  Additions to the
# original: the start marker + cancel check (the program must know the helper runs), a note for the next start when the
# update fails, and no rollback unless a complete backup exists.  tests/test_update_system.py pins all of it.
_UPDATE_SCRIPT_TEMPLATE = r"""$ErrorActionPreference = 'Stop'
$log = Join-Path $env:TEMP 'Planning_Update.log'
$notice = @@NOTICE@@
$newVersion = @@VERSION@@
# First: tell the program that the helper is running (it waits for this before it closes itself).
try { New-Item -ItemType File -Path @@STARTED@@ -Force | Out-Null } catch { }
function Stop-IfCancelled {
    # The program did not see the marker in time and withdrew the update: a helper that only now got started
    # (a slow antivirus scan) must not touch the installation while the program may still be open.
    if (Test-Path -LiteralPath @@CANCEL@@) {
        "The program withdrew this update (the helper started too late); nothing was changed." | Out-File -FilePath $log -Append
        Remove-Item -LiteralPath @@ZIP@@ -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath @@STAGE@@ -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}
if (Stop-IfCancelled) { exit }
# Give the old process time to fully exit and release its file locks, then
# explicitly wait until no old Planning process remains before copying. The
# fixed delay alone was not sufficient on slower machines/antivirus scans.
Start-Sleep -Seconds @@INITIAL_DELAY@@
for ($check = 1; $check -le @@EXIT_CHECKS@@; $check++) {
    if (-not (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds @@EXIT_INTERVAL@@
}
if (Stop-IfCancelled) { exit }
$source = @@SOURCE@@
$target = @@TARGET@@
$backup = @@BACKUP@@
$exePath = @@EXE@@
$script:backupDone = $false
function Write-Notice([string]$reason) {
    # Read by the program at its next start and shown once (utility.updater.consume_update_failure_notice).
    try { "version=$newVersion`r`nreason=$reason`r`nlog=$log" | Out-File -FilePath $notice -Encoding UTF8 } catch { }
}
function Restore-Backup {
    # Never let a rollback failure propagate out under $ErrorActionPreference
    # = 'Stop' -- that would skip the relaunch right after it and leave
    # nothing running at all. Best-effort is still far better than a silent,
    # total failure here.
    if (-not $script:backupDone) {
        "No complete backup of the previous version exists: nothing is deleted." | Out-File -FilePath $log -Append
        return
    }
    try {
        Get-ChildItem -LiteralPath $target -Force | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue
        Get-ChildItem -LiteralPath $backup -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force -ErrorAction SilentlyContinue
        }
    } catch { $_ | Out-File -FilePath $log -Append }
}
function Start-Planning {
    # Planning.exe itself should never run as Administrator ongoing -- only
    # copying into Program Files needs that. When this whole script runs
    # elevated (see _needs_elevation/_run_update_script), a plain
    # Start-Process would launch Planning.exe elevated too, and an elevated
    # GUI started from a background context is subject to Windows'
    # focus-stealing prevention: it runs but never comes to the front,
    # which looks exactly like "the app did not reopen". Shell.Application's
    # ShellExecute hands the launch to the already-running, non-elevated
    # explorer.exe instead, so the new process gets a normal-user token.
    # It doesn't return a PID, so success here just means "launch was
    # requested"; the caller's own wait loop (polls by process name) is what
    # confirms it actually came up.
    try {
        $shellApp = New-Object -ComObject "Shell.Application"
        $shellApp.ShellExecute($exePath, "", $target, "open", 1)
        return $true
    } catch { $_ | Out-File -FilePath $log -Append }
    try {
        $started = Start-Process -FilePath $exePath -WorkingDirectory $target -PassThru -ErrorAction Stop
        Start-Sleep -Seconds 2
        if (Get-Process -Id $started.Id -ErrorAction SilentlyContinue) { return $true }
    } catch { $_ | Out-File -FilePath $log -Append }
    try {
        Start-Process -FilePath 'cmd.exe' -WorkingDirectory $target -WindowStyle Hidden -ArgumentList @('/c', 'start', '""', $exePath) -ErrorAction Stop
        return $true
    } catch { $_ | Out-File -FilePath $log -Append; return $false }
}
try {
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    Get-ChildItem -LiteralPath $target -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $backup -Recurse -Force
    }
    # A rollback is only allowed to delete the installation when this complete copy exists.
    $inBackup = @(Get-ChildItem -LiteralPath $backup -Recurse -Force -File).Count
    $inTarget = @(Get-ChildItem -LiteralPath $target -Recurse -Force -File).Count
    if ($inBackup -lt $inTarget) { throw "The backup of the current version is incomplete ($inBackup of $inTarget files), so nothing was changed." }
    $script:backupDone = $true

    $copied = $false
    $lastError = ''
    for ($attempt = 1; $attempt -le @@COPY_ATTEMPTS@@; $attempt++) {
        try {
            Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force -ErrorAction Stop
            }
            if (Test-Path -LiteralPath $exePath) {
                $copied = $true
                break
            }
            $lastError = 'Planning.exe was not in place after the copy (an antivirus program may have removed it).'
        } catch {
            $_ | Out-File -FilePath $log -Append
            $lastError = [string]$_.Exception.Message
            Start-Sleep -Seconds @@COPY_INTERVAL@@
        }
    }

    if ($copied) {
        $versionPath = Join-Path $target 'version.txt'
        $versionValue = $newVersion
        $versionTemp = Join-Path $target ('.version.' + $PID + '.tmp')
        # ASCII: a version is digits and dots, and Windows PowerShell's "UTF8" would add a byte order mark.
        Set-Content -LiteralPath $versionTemp -Value $versionValue -Encoding ASCII
        Move-Item -LiteralPath $versionTemp -Destination $versionPath -Force
        $writtenVersion = (Get-Content -LiteralPath $versionPath -Raw).Trim().TrimStart('v','V')
        if ($writtenVersion -ne $versionValue.Trim().TrimStart('v','V')) { throw "version.txt verification failed: '$writtenVersion'" }
        if (-not (Start-Planning)) { throw "Planning.exe could not be started after update" }
        # Antivirus commonly intercepts a freshly-written, unsigned exe on
        # its first launch -- it can run its own scan/sandbox pass, kill
        # that first process, and start a *different* one afterwards, on
        # top of an already slower cold start. Watching one specific PID
        # would misread that AV cycle as a crash, and a short fixed wait
        # isn't enough either -- this has been observed taking close to a
        # minute in practice. So instead: poll by process name (survives
        # the PID changing under AV) for up to 3 minutes, and succeed the
        # moment Planning.exe is seen running even once -- a genuine crash
        # never shows up running at all, no matter how long or how many
        # times checked.
        $sawRunning = $false
        for ($check = 1; $check -le @@START_CHECKS@@; $check++) {
            Start-Sleep -Seconds @@START_INTERVAL@@
            if (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue) {
                $sawRunning = $true
                break
            }
        }
        if (-not $sawRunning) {
            "New version never started running within 3 minutes -- rolling back to the previous version" | Out-File -FilePath $log -Append
            Restore-Backup
            Start-Planning | Out-Null
            Write-Notice 'The new version did not start (an antivirus program may have blocked it), so the previous version was restored.'
        } else {
            Remove-Item -LiteralPath $notice -Force -ErrorAction SilentlyContinue
        }
    } else {
        "Update copy never succeeded after @@COPY_ATTEMPTS@@ attempts -- rolling back to the previous version" | Out-File -FilePath $log -Append
        Restore-Backup
        Start-Planning | Out-Null
        Write-Notice ('The new files could not be copied completely: ' + $lastError)
    }
    } catch {
        $_ | Out-File -FilePath $log -Append
        # Whatever failed above, always try to leave *something* running --
        # closing Planning to update and then leaving nothing open at all,
        # not even the old version, is the one outcome worse than a failed
        # update.
        Restore-Backup
        Start-Planning | Out-Null
        Write-Notice ([string]$_.Exception.Message)
    }
Remove-Item -LiteralPath @@ZIP@@ -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath @@STAGE@@ -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
"""


def build_update_script(*, source_dir: Path, install_dir: Path, backup_dir: Path, exe_path: Path, new_version: str,
                        zip_path: Path, stage_root: Path, notice_path: Path | None = None, started_path: Path | None = None,
                        cancel_path: Path | None = None, initial_delay: int = 5, exit_checks: int = 30, exit_interval: int = 2,
                        copy_attempts: int = 20, copy_interval: int = 2, start_checks: int = 36, start_interval: int = 5) -> str:
    """The PowerShell helper for one update (the timing arguments exist for the tests; the defaults are the production values)."""
    values = {
        "NOTICE": _powershell_quote(notice_path or UPDATE_FAILURE_NOTICE),
        "VERSION": _powershell_quote(new_version),
        "STARTED": _powershell_quote(started_path or stage_root / "helper_started.txt"),
        "CANCEL": _powershell_quote(cancel_path or stage_root / "helper_cancel.txt"),
        "ZIP": _powershell_quote(zip_path), "STAGE": _powershell_quote(stage_root),
        "SOURCE": _powershell_quote(source_dir), "TARGET": _powershell_quote(install_dir),
        "BACKUP": _powershell_quote(backup_dir), "EXE": _powershell_quote(exe_path),
        "INITIAL_DELAY": str(int(initial_delay)), "EXIT_CHECKS": str(int(exit_checks)), "EXIT_INTERVAL": str(int(exit_interval)),
        "COPY_ATTEMPTS": str(int(copy_attempts)), "COPY_INTERVAL": str(int(copy_interval)),
        "START_CHECKS": str(int(start_checks)), "START_INTERVAL": str(int(start_interval)),
    }
    script = _UPDATE_SCRIPT_TEMPLATE
    for name, value in values.items():
        script = script.replace(f"@@{name}@@", value)
    return script


# How long the program waits, before it closes itself, for the update helper to prove that it is running.  If antivirus or a
# Windows policy stops PowerShell / the script, nothing else would ever tell the user: the program would simply disappear.
HELPER_START_TIMEOUT_SECONDS = 25            # the helper starts hidden
HELPER_START_TIMEOUT_ELEVATED_SECONDS = 180  # ... or behind the Windows "Do you want to allow this app" prompt, which waits for a click
HELPER_POLL_SECONDS = 0.2


@dataclass(frozen=True)
class UpdateLaunch:
    """What install_update started: the program waits for ``started_marker`` before it closes, and ``cancel`` withdraws the update."""

    started_marker: Path
    cancel_marker: Path
    stage_root: Path
    script_path: Path
    elevated: bool

    @property
    def timeout(self) -> float:
        return HELPER_START_TIMEOUT_ELEVATED_SECONDS if self.elevated else HELPER_START_TIMEOUT_SECONDS

    def wait_until_started(self, pump: Callable[[], None] | None = None, *, timeout: float | None = None,
                           sleep: Callable[[float], None] = time.sleep, clock: Callable[[], float] = time.monotonic) -> bool:
        """True as soon as the helper has written its marker (it is running and will take over), False after the timeout.

        ``pump`` is called every poll (the window passes its ``update`` so it stays responsive while waiting).
        """
        deadline = clock() + (self.timeout if timeout is None else timeout)
        while True:
            if self.started_marker.exists():
                return True
            if clock() >= deadline:
                return False
            if pump is not None:
                pump()
            sleep(HELPER_POLL_SECONDS)

    def cancel(self) -> None:
        """The helper did not start in time: a helper that starts LATER must find this and leave everything as it is."""
        try:
            self.cancel_marker.write_text("cancelled by the program\n", encoding="utf-8")
        except OSError:
            _app_logger.warning("Update: could not write the cancel marker %s", self.cancel_marker, exc_info=True)


def helper_not_started_message(launch: UpdateLaunch) -> str:
    """The text for the user when the update helper never started (the program stays open, nothing was changed)."""
    return (
        "The update could not be started, so nothing was changed and Planning stays open.\n\n"
        "Windows or an antivirus program most likely blocked the update helper (a PowerShell script that Planning writes to "
        f"{launch.script_path.parent}). Allow it, or add an exception for that folder and for powershell.exe, then try again.\n\n"
        + ("The Windows permission prompt was not approved in time. " if launch.elevated else "")
        + f"Details: {Path(tempfile.gettempdir()) / 'Planning_Update.log'}"
    )


def install_update(zip_path: Path, install_dir: Path, new_version: str) -> UpdateLaunch:
    """Stage a ZIP update and start a hidden process that replaces files later.

    The running EXE cannot replace itself. The generated PowerShell helper
    waits for Planning to exit, backs up the current installation, copies
    the new application files over it, writes ``new_version`` (the GitHub release tag) into
    version.txt, starts the new EXE, and verifies it actually stays running --
    if the new build crashes immediately on launch, or the file copy never
    succeeds, it automatically restores the backup and relaunches the
    previous, known-working version instead of leaving the install broken or,
    worse, leaving nothing running at all.  User settings/data live in AppData
    and are never touched by either the update or the rollback.

    install_dir commonly needs Administrator rights (Program Files) that
    this process does not itself have, so the helper script is launched
    elevated (UAC prompt) whenever a real write probe shows install_dir
    isn't writable as-is.

    Returns an ``UpdateLaunch``: the caller waits for the helper's start marker before it closes the program.
    """
    if not zip_path.is_file():
        raise FileNotFoundError(zip_path)
    if not getattr(sys, "frozen", False):
        raise RuntimeError("Automatic updates are available only in the installed Windows version.")

    elevated = _needs_elevation(install_dir)
    stage_root = Path(tempfile.mkdtemp(prefix="Planning_Update_"))
    try:
        _safe_extract(zip_path, stage_root)
        executables = sorted(stage_root.rglob("Planning.exe"), key=lambda path: len(path.parts))
        if not executables:
            raise RuntimeError("The update ZIP must contain Planning.exe.")
        # Accept all common ZIP layouts: Planning.exe at the root, inside a
        # Planning folder, or inside an archived dist/Planning folder.
        source_dir = executables[0].parent
        _check_package_is_complete(source_dir)

        script_path = stage_root.parent / f"Planning_Update_{os.getpid()}.ps1"
        exe_path = install_dir / "Planning.exe"
        # A sibling of install_dir, not inside it, so clearing/restoring
        # install_dir during a rollback never touches the backup itself.
        # Overwritten fresh on every update -- always exactly one, most
        # recent known-good version to fall back to.
        backup_dir = install_dir.parent / "Planning_Backup"
        script = build_update_script(
            source_dir=source_dir, install_dir=install_dir, backup_dir=backup_dir, exe_path=exe_path,
            new_version=new_version, zip_path=zip_path, stage_root=stage_root,
        )
        # With a byte order mark: Windows PowerShell 5.1 reads a BOM-less script as ANSI, which garbles a path that contains
        # non-ASCII characters (a user name in Arabic, say).
        script_path.write_text(script, encoding="utf-8-sig")
        # CREATE_NO_WINDOW alone only hides the console -- it doesn't
        # detach the process from anything. If Planning.exe is running
        # inside a Windows Job Object (common under some launchers, remote
        # sessions, or security software), closing the parent can silently
        # kill this helper along with it before it ever gets to run,
        # leaving the update never applied and nothing relaunched at all.
        # CREATE_BREAKAWAY_FROM_JOB + CREATE_NEW_PROCESS_GROUP make sure
        # this process survives the parent's exit regardless. Irrelevant
        # (and unavailable) for the elevated/ShellExecuteW path -- a
        # UAC-elevated process is already its own top-level session.
        creation_flags = (
            getattr(subprocess, "CREATE_NO_WINDOW", 0)
            | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
            | getattr(subprocess, "CREATE_BREAKAWAY_FROM_JOB", 0)
        )
        _app_logger.info(
            "Update to %s: package checked (installed version will be the release tag), starting the helper%s; its log: %s",
            new_version, " with administrator rights" if elevated else "", Path(tempfile.gettempdir()) / "Planning_Update.log",
        )
        _run_update_script(script_path, creation_flags, elevated)
    except Exception:
        shutil.rmtree(stage_root, ignore_errors=True)
        zip_path.unlink(missing_ok=True)
        raise
    return UpdateLaunch(stage_root / "helper_started.txt", stage_root / "helper_cancel.txt", stage_root, script_path, elevated)
