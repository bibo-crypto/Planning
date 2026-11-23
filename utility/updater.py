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
    # ``build.bat`` always creates this exact full-program archive. Prefer it
    # over unrelated ZIP attachments (for example a log or source archive).
    candidates.sort(key=lambda item: (Path(item[0]).name.casefold() != "planning.zip", item[0].casefold()))
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


def _check_package_is_complete(source_dir: Path, expected_version: str | None = None) -> None:
    """Refuse a package that could not start, before anything of the installed version is touched.

    A PyInstaller build keeps the Python DLL in ``_internal``; an update ZIP without it would replace a working
    installation with one that stops at "Failed to load Python DLL ...".
    """
    exe = source_dir / "Planning.exe"
    if not exe.is_file() or exe.stat().st_size == 0:
        raise RuntimeError("The update ZIP must contain Planning.exe.")
    # The release tag is the source of truth for the installed version.  The
    # archive deliberately has a stable name (Planning.zip), and may have
    # been built while its bundled _internal/version.txt still had an older
    # value.  Write the external marker into staging before the manifest is
    # made, so the copied application always reports the GitHub tag.
    version_path = source_dir / "version.txt"
    if expected_version is not None:
        _canonicalize_staged_version_file(version_path, expected_version)
        # A PyInstaller build also carries its own copy in _internal; the program reads the external one first and
        # falls back to this one, so both must say the same thing or a stale value could surface later.
        internal_version = source_dir / "_internal" / "version.txt"
        if internal_version.is_file():
            _canonicalize_staged_version_file(internal_version, expected_version)
    elif version_path.is_file():
        _canonicalize_staged_version_file(version_path)
    internal = source_dir / "_internal"
    if not internal.is_dir() or not any(internal.glob("python3*.dll")):
        raise RuntimeError(
            "The update package is incomplete (the Python DLL is missing from _internal), so it was not installed. "
            "The GitHub release must contain the WHOLE program folder: upload dist\\Planning.zip made by "
            "\"build.bat\", not Planning.exe alone."
        )


def _canonicalize_staged_version_file(path: Path, expected_version: str | None = None) -> None:
    """Make the staged version marker deterministic before the manifest is read.

    With an expected version, the GitHub release tag is authoritative and is
    written even when the archive has no marker or an older bundled marker.
    Otherwise normalize an existing marker. Canonical form is UTF-8 without a
    BOM and one LF terminator.
    """
    if expected_version is not None:
        value = str(expected_version).strip().lstrip("vV")
    else:
        try:
            raw = path.read_bytes()
            value = raw.decode("utf-8-sig").replace("\r\n", "\n").replace("\r", "\n").strip().lstrip("vV")
        except (OSError, UnicodeDecodeError) as exc:
            raise RuntimeError("The update package contains an unreadable version.txt.") from exc
    if not value or not all(part.isdigit() for part in value.split(".")):
        raise RuntimeError("The update version is invalid.")
    try:
        path.write_bytes((value + "\n").encode("utf-8"))
    except OSError as exc:
        raise RuntimeError("The staged update version.txt could not be normalized.") from exc


# The PowerShell helper.  Plain text with @@NAME@@ placeholders (not an f-string: PowerShell is full of braces).
_UPDATE_SCRIPT_TEMPLATE = r"""$ErrorActionPreference = 'Stop'
# FIRST thing: tell the program the helper is running (it waits for this before it closes itself).
try { [System.IO.File]::WriteAllText(@@STARTED@@, 'started') } catch { }
$log = Join-Path $env:TEMP 'Planning_Update.log'
function Write-UpdateLog($message) {
    # a log that cannot be written (full disk, antivirus) must never stop the update
    try { ("{0}  {1}" -f (Get-Date -Format 's'), $message) | Out-File -FilePath $log -Append } catch { }
}
$script:clock = [System.Diagnostics.Stopwatch]::StartNew()
Write-UpdateLog ("Update helper started: version {0}, installed in {1}" -f @@VERSION@@, @@TARGET@@)
function Test-Cancelled {
    # The program waited for the marker above, did not see it in time and withdrew the update: a helper that only now
    # got started (a slow antivirus scan) must not touch the installation while the program is still open.
    if (Test-Path -LiteralPath @@CANCEL@@) {
        Write-UpdateLog 'The program withdrew this update (the helper started too late); nothing was changed.'
        Remove-Item -LiteralPath @@ZIP@@ -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath @@STAGE@@ -Recurse -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}
if (Test-Cancelled) { exit 0 }
# Give the old process time to fully exit and release its file locks, then
# explicitly wait until no old Planning process remains before copying. The
# fixed delay alone was not sufficient on slower machines/antivirus scans.
Start-Sleep -Seconds @@INITIAL_DELAY@@
for ($check = 1; $check -le @@EXIT_CHECKS@@; $check++) {
    if (-not (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue)) { break }
    Start-Sleep -Seconds @@EXIT_INTERVAL@@
}
if (Test-Cancelled) { exit 0 }
$source = @@SOURCE@@
$target = @@TARGET@@
$backup = @@BACKUP@@
$exePath = @@EXE@@
function Get-RelativeFiles([string]$root) {
    # Every file below $root as @{Relative; Length}, built from item NAMES only.  Cutting a prefix off full paths is not safe:
    # Windows PowerShell 5.1 returns long names in FullName but keeps an 8.3 short form (MEGAST~1) in Resolve-Path, so the
    # prefix was 2 characters too short and every file looked "missing" ("bj\planning.exe") -- the update never completed.
    $found = New-Object System.Collections.ArrayList
    $pending = New-Object System.Collections.Stack
    $pending.Push('')
    while ($pending.Count -gt 0) {
        $relativeDir = [string]$pending.Pop()
        $dir = if ($relativeDir -eq '') { $root } else { Join-Path $root $relativeDir }
        foreach ($item in (Get-ChildItem -LiteralPath $dir -Force)) {
            $relative = if ($relativeDir -eq '') { $item.Name } else { Join-Path $relativeDir $item.Name }
            if ($item.PSIsContainer) {
                if (-not ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) { $pending.Push($relative) }
            } else {
                [void]$found.Add([pscustomobject]@{ Relative = $relative })
            }
        }
    }
    return ,$found
}
function Get-RelativeKey([string]$relative) {
    # Relative keys are the only identity used by the transaction.  They are
    # made from child item names (never FullName/Resolve-Path), use one slash
    # convention, and compare case-insensitively like the Windows filesystem.
    return (($relative -replace '/', '\').TrimStart('\')).ToLowerInvariant()
}
function Get-FileMap([string]$root) {
    # relative path (normalised lower case) -> SHA-256, for every file below $root
    $map = @{}
    foreach ($file in (Get-RelativeFiles $root)) {
        $path = Join-Path $root $file.Relative
        $map[(Get-RelativeKey $file.Relative)] = (Get-FileHash -LiteralPath $path -Algorithm SHA256 -ErrorAction Stop).Hash.ToLowerInvariant()
    }
    return $map
}
function Find-MissingFromMap($expected, [string]$actualRoot) {
    # the files of a recorded file list that are absent or have another digest
    $actual = Get-FileMap $actualRoot
    $problems = @()
    foreach ($key in $expected.Keys) {
        if (-not $actual.ContainsKey($key)) { $problems += "missing: $key" }
        elseif ($actual[$key] -ne $expected[$key]) { $problems += "different SHA-256: $key" }
    }
    return ,$problems
}
function Find-MissingFiles([string]$expectedRoot, [string]$actualRoot) {
    # the files of $expectedRoot that are absent from $actualRoot or have another size
    return ,(Find-MissingFromMap (Get-FileMap $expectedRoot) $actualRoot)
}
# The installation may only be wiped for a rollback when the backup of it was copied completely AND verified;
# otherwise a rollback would replace a healthy installation with a partial copy (a missing python DLL, no Planning.exe).
$newVersion = @@VERSION@@
$notice = @@NOTICE@@
Remove-Item -LiteralPath $notice -Force -ErrorAction SilentlyContinue
$script:rolledBack = $false
function Set-FinalMessage([string]$reason) {
    # What the user is told in a Windows message box once everything else is done: why, and what state the installation is in.
    $running = [bool](Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue)
    if ($script:rolledBack -and $running) { $state = 'The previous version was restored and is running again.' }
    elseif ($script:rolledBack) { $state = 'The previous version was restored, but it could not be started automatically - please start Planning yourself.' }
    elseif (-not $script:backupVerified) { $state = 'The installation was left exactly as it was.' }
    else { $state = "The previous version could NOT be restored completely; a full copy of it is in $backup" }
    $script:finalMessage = "Planning could not be updated to $newVersion.`r`n`r`n$reason`r`n`r`n$state`r`n`r`nIf an antivirus program is blocking the update, allow Planning.exe and PowerShell scripts in $target and try again.`r`n`r`nDetails: $log"
}
function Show-UpdateMessage([string]$text) {
    try {
        Add-Type -AssemblyName System.Windows.Forms -ErrorAction Stop
        [void][System.Windows.Forms.MessageBox]::Show($text, 'Planning update', 'OK', 'Warning')
    } catch { Write-UpdateLog ('Could not show the message: ' + $_.Exception.Message) }
}
function Write-UpdateFailure([string]$reason) {
    # Leaves a note for the program: on its next start it tells the user the update was not installed, and why.
    try {
        $noticeDir = Split-Path -Parent $notice
        if (-not (Test-Path -LiteralPath $noticeDir)) { New-Item -ItemType Directory -Path $noticeDir -Force | Out-Null }
        $text = "version=$newVersion`r`ntime=$(Get-Date -Format 's')`r`nlog=$log`r`nreason=$reason`r`n"
        [System.IO.File]::WriteAllText($notice, $text, (New-Object System.Text.UTF8Encoding($false)))
    } catch { }
}
$script:backupVerified = $false
$script:previousFiles = $null
function Restore-Backup {
    # Never let a rollback failure propagate out under $ErrorActionPreference
    # = 'Stop' -- that would skip the Start-Process relaunch right after it
    # and leave nothing running at all. Best-effort is still far better than
    # a silent, total failure here.
    if (-not $script:backupVerified) {
        Write-UpdateLog "No verified backup of the previous version exists: the installation is left exactly as it is (nothing is deleted)."
        return
    }
    try {
        Get-ChildItem -LiteralPath $backup -Force | ForEach-Object {
            Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force -ErrorAction Continue
        }
        # checked against the file list recorded before the update touched anything (a backup that lost a file since
        # it was verified must not be mistaken for a complete one)
        $problems = Find-MissingFromMap $script:previousFiles $target
        if ($problems.Count -gt 0) {
            Write-UpdateLog ("Rollback incomplete: {0} file(s) of the previous version could not be restored (the full copy stays in {1}):" -f $problems.Count, $backup)
            $problems | Select-Object -First 10 | ForEach-Object { Write-UpdateLog $_ }
            return
        }
        # restored and verified: only now remove the files that exist solely in the new version
        $keep = $script:previousFiles
        foreach ($file in (Get-RelativeFiles $target)) {
            if (-not $keep.ContainsKey((Get-RelativeKey $file.Relative))) {
                Remove-Item -LiteralPath (Join-Path $target $file.Relative) -Force -ErrorAction SilentlyContinue
            }
        }
        Write-UpdateLog "Rolled back to the previous version (verified)."
        $script:rolledBack = $true
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
    # requested"; the caller's own wait loop (polls by process name, up to
    # 3 minutes) is what confirms it actually came up.
    for ($launchAttempt = 1; $launchAttempt -le 3; $launchAttempt++) {
        try {
            $shellApp = New-Object -ComObject "Shell.Application"
            $shellApp.ShellExecute($exePath, "", $target, "open", 1)
        } catch { $_ | Out-File -FilePath $log -Append }

        Start-Sleep -Seconds 2
        if (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue) { return $true }

        try {
            $started = Start-Process -FilePath $exePath -WorkingDirectory $target -PassThru -ErrorAction Stop
            Start-Sleep -Seconds 2
            if (Get-Process -Id $started.Id -ErrorAction SilentlyContinue) { return $true }
        } catch { $_ | Out-File -FilePath $log -Append }

        try {
            Start-Process -FilePath 'cmd.exe' -WorkingDirectory $target -WindowStyle Hidden -ArgumentList @('/c', 'start', '""', $exePath) -ErrorAction Stop
            Start-Sleep -Seconds 2
        } catch { $_ | Out-File -FilePath $log -Append }

        if (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}
try {
    if (Test-Path -LiteralPath $backup) { Remove-Item -LiteralPath $backup -Recurse -Force -ErrorAction SilentlyContinue }
    New-Item -ItemType Directory -Path $backup -Force | Out-Null
    $previous = Get-FileMap $target
    Get-ChildItem -LiteralPath $target -Force | ForEach-Object {
        Copy-Item -LiteralPath $_.FullName -Destination $backup -Recurse -Force
    }
    $problems = Find-MissingFromMap $previous $backup
    if ($problems.Count -gt 0) {
        throw ("The backup of the current version is incomplete ({0} file(s), for example {1}); the update was cancelled before anything was changed." -f $problems.Count, $problems[0])
    }
    $script:previousFiles = $previous
    $script:backupVerified = $true
    Write-UpdateLog ("Backup of the current version copied and verified ({0} file(s), {1:N0} s)." -f @($previous.Keys).Count, $script:clock.Elapsed.TotalSeconds)

    $copied = $false
    $lastProblem = ''
    for ($attempt = 1; $attempt -le @@ATTEMPTS@@; $attempt++) {
        try {
            Get-ChildItem -LiteralPath $source -Force | ForEach-Object {
                Copy-Item -LiteralPath $_.FullName -Destination $target -Recurse -Force -ErrorAction Stop
            }
            # the copy only counts when EVERY file of the new version is there (Planning.exe alone proves nothing:
            # the old one already exists)
            $problems = Find-MissingFiles $source $target
            if ($problems.Count -eq 0) {
                $copied = $true
                Write-UpdateLog ("New version copied and verified (attempt {0}, {1:N0} s since the start)." -f $attempt, $script:clock.Elapsed.TotalSeconds)
                break
            }
            $lastProblem = ("{0} file(s) of the new version are not in place yet, for example {1}" -f $problems.Count, $problems[0])
            Write-UpdateLog ("Copy attempt {0}: {1}" -f $attempt, $lastProblem)
            Start-Sleep -Seconds @@RETRY_DELAY@@
        } catch {
            $lastProblem = [string]$_.Exception.Message
            $_ | Out-File -FilePath $log -Append
            Start-Sleep -Seconds @@RETRY_DELAY@@
        }
    }

    if ($copied) {
        $versionPath = Join-Path $target 'version.txt'
        $versionValue = @@VERSION@@
        # The release tag is authoritative. Write it again after the whole
        # copy, so a missing or stale marker in the archive cannot leave the
        # installed application on the old version.
        [System.IO.File]::WriteAllText($versionPath, $versionValue.Trim().TrimStart('v','V') + "`n", (New-Object System.Text.UTF8Encoding($false)))
        $writtenVersion = ([System.IO.File]::ReadAllText($versionPath)).Trim().TrimStart('v','V')
        if ($writtenVersion -ne $versionValue.Trim().TrimStart('v','V')) { throw "version.txt verification failed: '$writtenVersion'" }
        Write-UpdateLog ("version.txt now says {0}." -f $writtenVersion)
        if (-not (Start-Planning)) { throw "Planning.exe could not be started after update" }
        # Antivirus commonly intercepts a freshly-written, unsigned exe on
        # its first launch -- it can run its own scan/sandbox pass, kill
        # that first process, and start a *different* one afterwards, on
        # top of an already slower cold start. Watching one specific PID
        # (Start-Process -PassThru) would misread that AV cycle as a crash,
        # and a short fixed wait isn't enough either -- this has been
        # observed taking close to a minute in practice. So instead: poll
        # by process name (survives the PID changing under AV) for up to 3
        # minutes, and succeed the moment Planning.exe is seen running even
        # once -- a genuine crash never shows up running at all, no matter
        # how long or how many times checked.
        $sawRunning = $false
        for ($check = 1; $check -le @@START_CHECKS@@; $check++) {
            Start-Sleep -Seconds @@START_INTERVAL@@
            if (Get-Process -Name 'Planning','Planing' -ErrorAction SilentlyContinue) {
                $sawRunning = $true
                Write-UpdateLog ("The new version is running. Update finished ({0:N0} s)." -f $script:clock.Elapsed.TotalSeconds)
                break
            }
        }
        if (-not $sawRunning) {
            "New version never started running within 3 minutes -- rolling back to the previous version" | Out-File -FilePath $log -Append
            Write-UpdateFailure 'The new version did not start, so the previous version was restored.'
            Restore-Backup
            Start-Planning | Out-Null
            Set-FinalMessage 'The new version did not start (an antivirus program may have blocked it).'
        }
    } else {
        "Update copy never succeeded after @@ATTEMPTS@@ attempts -- rolling back to the previous version" | Out-File -FilePath $log -Append
        Write-UpdateFailure ('The new files could not be copied completely: ' + $lastProblem)
        Restore-Backup
        Start-Planning | Out-Null
        Set-FinalMessage ('The new files could not be copied completely (an antivirus program may have removed or locked one): ' + $lastProblem)
    }
    } catch {
        $_ | Out-File -FilePath $log -Append
        Write-UpdateFailure ([string]$_.Exception.Message)
        # Whatever failed above, always try to leave *something* running --
        # closing Planning to update and then leaving nothing open at all,
        # not even the old version, is the one outcome worse than a failed
        # update.
        Restore-Backup
        Start-Planning | Out-Null
        Set-FinalMessage ([string]$_.Exception.Message)
    }
Remove-Item -LiteralPath @@ZIP@@ -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath @@STAGE@@ -Recurse -Force -ErrorAction SilentlyContinue
Remove-Item -LiteralPath $PSCommandPath -Force -ErrorAction SilentlyContinue
if ($script:finalMessage) { Show-UpdateMessage $script:finalMessage }
"""


def build_update_script(*, source_dir: Path, install_dir: Path, backup_dir: Path, exe_path: Path, new_version: str,
                        zip_path: Path, stage_root: Path, notice_path: Path | None = None, started_path: Path | None = None,
                        cancel_path: Path | None = None, initial_delay: int = 5, exit_checks: int = 30,
                        exit_interval: int = 2, attempts: int = 20, retry_delay: int = 2,
                        start_checks: int = 36, start_interval: int = 5) -> str:
    """The text of the PowerShell helper that replaces the installed files once Planning has exited.

    The timing arguments only exist so the script can be run quickly in tests; the defaults are what the program uses.
    """
    values = {
        "SOURCE": _powershell_quote(source_dir), "TARGET": _powershell_quote(install_dir), "BACKUP": _powershell_quote(backup_dir),
        "EXE": _powershell_quote(exe_path), "VERSION": _powershell_quote(new_version), "ZIP": _powershell_quote(zip_path),
        "STAGE": _powershell_quote(stage_root), "STARTED": _powershell_quote(started_path or stage_root / "helper_started.txt"),
        "CANCEL": _powershell_quote(cancel_path or stage_root / "helper_cancel.txt"), "NOTICE": _powershell_quote(notice_path or UPDATE_FAILURE_NOTICE), "INITIAL_DELAY": str(int(initial_delay)), "EXIT_CHECKS": str(int(exit_checks)),
        "EXIT_INTERVAL": str(int(exit_interval)), "ATTEMPTS": str(int(attempts)), "RETRY_DELAY": str(int(retry_delay)),
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
    the new application files over it, starts the new EXE, and verifies it
    actually stays running -- if the new build crashes immediately on
    launch, or the file copy never succeeds, it automatically restores the
    backup and relaunches the previous, known-working version instead of
    leaving the install broken or, worse, leaving nothing running at all.
    User settings/data live in AppData and are never touched by either the
    update or the rollback.

    install_dir commonly needs Administrator rights (Program Files) that
    this process does not itself have, so the helper script is launched
    elevated (UAC prompt) whenever a real write probe shows install_dir
    isn't writable as-is -- otherwise every step below fails with Access
    Denied, including the rollback's own copy-back, silently.
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
        _check_package_is_complete(source_dir, new_version)

        # The bootstrap is created before the old installation is touched and
        # runs independently after this process exits.  It is deliberately
        # not loaded from the new ZIP: replacing updater.py cannot repair the
        # transaction that is already in flight.
        script_path = stage_root.parent / f"Planning_UpdateBootstrap_{os.getpid()}.ps1"
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
        script_path.write_text(script, encoding="utf-8")
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
