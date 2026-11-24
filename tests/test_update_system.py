"""Regression tests for the Setup-based updater and its release package."""
import json
import re
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from utility import updater
from utility.updater import ReleaseInfo

ROOT = Path(__file__).resolve().parent.parent


def _minimal_pe() -> bytes:
    payload = bytearray(0x44)
    payload[:2] = b"MZ"
    payload[0x3C:0x40] = (0x40).to_bytes(4, "little")
    payload[0x40:0x44] = b"PE\0\0"
    return bytes(payload)


class _ApiResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _DownloadResponse:
    def __init__(self, body, content_length=None):
        self.body = body
        self.headers = {} if content_length is None else {"Content-Length": str(content_length)}

    def read(self, size):
        body, self.body = self.body, b""
        return body

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _release(name="Planning_Setup_v1.3.9.exe", url="https://example/setup.exe"):
    return ReleaseInfo(
        version="1.3.9",
        tag_name="v1.3.9",
        title="Planning",
        notes="",
        page_url="https://github.com/bibo-crypto/Planning/releases/tag/v1.3.9",
        installer_url=url,
        installer_name=name,
    )


def test_version_comparison_handles_tags_and_numeric_components():
    assert updater.is_newer_version("v1.3.10", "1.3.9")
    assert not updater.is_newer_version("v1.3.9", "1.3.9")
    assert updater.is_newer_version("v2.0.0", "1.99.99")


def test_release_picker_selects_setup_exe_and_never_uses_zip_or_unrelated_exe():
    assets = [
        {"name": "Planning_v1.3.9.zip", "browser_download_url": "zip"},
        {"name": "Notes.exe", "browser_download_url": "notes"},
        {"name": "Planning_Setup_v1.3.9.exe", "browser_download_url": "setup"},
    ]
    assert updater._choose_installer(assets) == ("Planning_Setup_v1.3.9.exe", "setup")
    assert updater._choose_installer([assets[0], assets[1]]) == ("", "")


@pytest.mark.parametrize(
    "tag, installed, expected",
    [("v1.3.9", "1.3.8", True), ("v1.3.9", "1.3.9", False), ("v1.3.9", "1.4.0", False)],
)
def test_latest_release_uses_tag_and_setup_asset(monkeypatch, tag, installed, expected):
    payload = {
        "tag_name": tag,
        "name": "Planning release",
        "body": "Release notes",
        "html_url": "https://example/release",
        "assets": [
            {"name": "Planning_v1.3.9.zip", "browser_download_url": "https://example/archive.zip"},
            {"name": "Planning_Setup_v1.3.9.exe", "browser_download_url": "https://example/setup.exe"},
        ],
    }
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: _ApiResponse(payload))
    monkeypatch.setattr(updater, "get_installed_version", lambda: installed)

    release = updater.fetch_latest_release()

    assert (release is not None) is expected
    if release:
        assert release.version == tag.lstrip("v")
        assert release.installer_name == "Planning_Setup_v1.3.9.exe"


def test_latest_release_without_setup_exe_is_not_offered(monkeypatch):
    payload = {
        "tag_name": "v1.3.9",
        "assets": [{"name": "Planning_v1.3.9.zip", "browser_download_url": "https://example/archive.zip"}],
    }
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: _ApiResponse(payload))
    monkeypatch.setattr(updater, "get_installed_version", lambda: "1.3.8")
    assert updater.fetch_latest_release() is None


def test_download_installer_accepts_complete_pe_and_reports_progress(monkeypatch):
    body = _minimal_pe()
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: _DownloadResponse(body, len(body)))
    progress = []

    installer = updater.download_installer(_release(), progress.append)
    try:
        assert installer.suffix == ".exe"
        assert installer.read_bytes() == body
        assert progress == [100]
    finally:
        installer.unlink(missing_ok=True)


def test_download_installer_rejects_truncated_file(monkeypatch):
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: _DownloadResponse(b"MZshort", 100))
    with pytest.raises(RuntimeError, match="Download incomplete"):
        updater.download_installer(_release())


def test_download_installer_rejects_non_pe_file(monkeypatch):
    monkeypatch.setattr(updater, "urlopen", lambda *args, **kwargs: _DownloadResponse(b"not an executable"))
    with pytest.raises(RuntimeError, match="valid Windows executable"):
        updater.download_installer(_release())


def test_download_installer_rejects_zip_asset_before_downloading():
    with pytest.raises(RuntimeError, match="Planning_Setup"):
        updater.download_installer(_release("Planning.zip", "https://example/archive.zip"))


def test_launch_installer_validates_the_file_before_launching(tmp_path):
    with pytest.raises(RuntimeError, match="missing or is not a valid Windows executable"):
        updater.launch_installer(tmp_path / "missing.exe", tmp_path)


@pytest.mark.skipif(sys.platform != "win32", reason="Setup launch is Windows-only")
def test_launch_installer_runs_in_user_context_for_writable_install(monkeypatch, tmp_path):
    installer = tmp_path / "Planning_Setup_v1.3.9.exe"
    installer.write_bytes(_minimal_pe())
    monkeypatch.setattr(updater, "_needs_elevation", lambda _directory: False)
    starts = []
    monkeypatch.setattr(updater.subprocess, "Popen", lambda *args, **kwargs: starts.append((args, kwargs)))

    updater.launch_installer(installer, tmp_path / "install")

    assert starts == [(([str(installer)],), {"cwd": str(tmp_path), "close_fds": True})]


@pytest.mark.skipif(sys.platform != "win32", reason="UAC launch is Windows-only")
@pytest.mark.parametrize("shell_result, raises", [(42, False), (5, True)])
def test_launch_installer_requests_uac_for_protected_install(monkeypatch, tmp_path, shell_result, raises):
    import ctypes

    installer = tmp_path / "Planning_Setup_v1.3.9.exe"
    installer.write_bytes(_minimal_pe())
    calls = []

    class Shell32:
        def ShellExecuteW(self, *args):
            calls.append(args)
            return shell_result

    monkeypatch.setattr(updater, "_needs_elevation", lambda _directory: True)
    monkeypatch.setattr(ctypes, "windll", SimpleNamespace(shell32=Shell32()), raising=False)

    if raises:
        with pytest.raises(RuntimeError, match="did not approve"):
            updater.launch_installer(installer, tmp_path / "Program Files" / "Planning")
    else:
        updater.launch_installer(installer, tmp_path / "Program Files" / "Planning")
        assert calls[0][1] == "runas" and calls[0][2] == str(installer)


def test_needs_elevation_detects_a_writable_install_directory(tmp_path):
    install = tmp_path / "install"
    install.mkdir()
    assert updater._needs_elevation(install) is False


def test_external_version_file_wins_and_accepts_a_bom(tmp_path, monkeypatch):
    install = tmp_path / "app"
    install.mkdir()
    version = install / "version.txt"
    version.write_bytes(b"\xef\xbb\xbf1.3.8\r\n")
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Planning.exe"))
    assert updater.get_installed_version() == "1.3.8"


def test_write_version_file_is_atomic_plain_utf8(tmp_path):
    path = updater.write_version_file("v1.3.9", tmp_path / "version.txt")
    assert path.read_bytes() == b"1.3.9\n"


def test_old_update_failure_notice_is_read_once(tmp_path, monkeypatch):
    notice = tmp_path / "update_failed.txt"
    notice.write_text("version=1.3.8\nreason=old updater failed\n", encoding="utf-8")
    monkeypatch.setattr(updater, "get_installed_version", lambda: "1.3.6")

    message = updater.consume_update_failure_notice(notice)

    assert "1.3.8" in message and "old updater failed" in message
    assert not notice.exists()
    assert updater.consume_update_failure_notice(notice) is None


def test_release_build_creates_both_zip_and_setup():
    text = (ROOT / "build.bat").read_bytes().decode("utf-8", errors="replace").replace("\r\n", "\n")
    assert 'if /i "%~1"=="zip" (' not in text
    assert "Compress-Archive -Path 'dist\\Planning\\*' -DestinationPath 'dist\\Planning.zip'" in text
    assert '"%ISCC_PATH%" installer.iss' in text
    assert 'Planning_Setup_v%PLANNING_VERSION%.exe' in text
    assert 'tools\\check_release_zip.py "dist\\Planning.zip"' in text
    assert "Planning_v!PLANNING_VERSION!.zip" not in text
    raw = (ROOT / "build.bat").read_bytes()
    assert raw.count(b"\r\n") == raw.count(b"\n"), "build.bat must keep CRLF line endings"


def test_release_documentation_requires_setup_executable_and_migration():
    text = (ROOT / "docs" / "RELEASE_STEPS.md").read_text(encoding="utf-8")
    for required in ("Planning_Setup_v", "Planning.zip", "build.bat", "manually", "Do not disable antivirus"):
        assert required in text
    assert "Planning_v<version>.zip" not in text


def test_release_versions_agree():
    version = (ROOT / "version.txt").read_text(encoding="utf-8").strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+", version)
    assert version == updater.DEFAULT_APP_VERSION
    assert f'#define AppVersion   "{version}"' in (ROOT / "installer.iss").read_text(encoding="utf-8")
