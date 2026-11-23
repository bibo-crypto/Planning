"""The GitHub release tag is the version the program has after an update.

How it works (and what these tests keep from changing again):

1. The tag of the latest release (``v1.3.7``) is the new version; the name and the version.txt inside the ZIP do not matter.
2. Before anything is touched, the updater writes the tag into the staged copy of ``version.txt`` (next to Planning.exe) and into
   ``_internal/version.txt`` when the package has one; the helper writes it once more after the whole copy has been verified.
3. At start-up the program reads the external ``version.txt`` first (``_internal`` only as a fallback), so it reports the tag,
   and the next check offers only a release that is newer than the tag.
4. A failed update changes nothing: the old version.txt stays with the old files.

The history this guards against: releases were published whose version.txt differed from the tag (and ZIPs with only
Planning.exe); the updater refused them, or an update installed but the program still reported the old number.
"""
import json
import re
import sys
import zipfile
from pathlib import Path

import pytest

from tests.test_update_script import Run, make_install, make_release, needs_pwsh, needs_shell, tree
from utility import updater

ROOT = Path(__file__).resolve().parent.parent


def _release_with_markers(tmp_path, root_marker, internal_marker):
    release = make_release(tmp_path)
    for path, raw in ((release / "version.txt", root_marker), (release / "_internal" / "version.txt", internal_marker)):
        if raw is None:
            path.unlink(missing_ok=True)
        else:
            path.write_bytes(raw)
    return release


# ------------------------------------------------------------------ 1+2. staging: the tag wins over whatever the ZIP says
@pytest.mark.parametrize("root_marker", [None, b"2.5.1", b"1.0.0\n", b"99.0.0\n", b"\xef\xbb\xbf1.2.3\r\n", b"garbage"],
                         ids=["absent", "same", "older", "newer", "bom-crlf", "not-a-version"])
@pytest.mark.parametrize("internal_marker", [None, b"1.3.6\n"], ids=["no-internal-marker", "stale-internal-marker"])
def test_the_tag_is_written_into_the_staged_markers_whatever_the_zip_contains(tmp_path, root_marker, internal_marker):
    release = _release_with_markers(tmp_path, root_marker, internal_marker)
    updater._check_package_is_complete(release, "2.5.1")                         # never raises because of the bundled version
    assert (release / "version.txt").read_bytes() == b"2.5.1\n"
    internal = release / "_internal" / "version.txt"
    if internal_marker is None:
        assert not internal.exists()                                             # no marker is invented inside _internal
    else:
        assert internal.read_bytes() == b"2.5.1\n"


@pytest.mark.parametrize("tag", ["v2.5.1", "V2.5.1", " v2.5.1 ", "2.5.1"])
def test_every_spelling_of_the_tag_gives_the_same_canonical_marker(tmp_path, tag):
    release = _release_with_markers(tmp_path, b"1.0.0", b"1.0.0")
    updater._check_package_is_complete(release, tag)
    assert (release / "version.txt").read_bytes() == b"2.5.1\n" == (release / "_internal" / "version.txt").read_bytes()


@pytest.mark.parametrize("tag", ["", "v", "latest", "1.3.x", "1.3-beta", "v1..2"])
def test_a_tag_that_is_not_a_version_is_refused_and_writes_nothing(tmp_path, tag):
    release = _release_with_markers(tmp_path, b"1.0.0\n", b"1.0.0\n")
    with pytest.raises(RuntimeError, match="version is invalid"):
        updater._check_package_is_complete(release, tag)
    assert (release / "version.txt").read_bytes() == b"1.0.0\n"


def test_the_tag_never_makes_an_incomplete_package_acceptable(tmp_path):
    release = make_release(tmp_path, with_dll=False)
    with pytest.raises(RuntimeError, match="Python DLL is missing") as caught:
        updater._check_package_is_complete(release, "2.5.1")
    assert "build.bat" in str(caught.value)                                       # says what to upload instead


# ------------------------------------------------------------------ 2. install_update hands the helper the tag, for every ZIP layout
def _zip_of(release, archive, prefix=""):
    with zipfile.ZipFile(archive, "w") as z:
        for path in release.rglob("*"):
            if path.is_file():
                z.write(path, prefix + path.relative_to(release).as_posix())
    return archive


@pytest.mark.parametrize("prefix", ["", "Planning/", "dist/Planning/"], ids=["flat", "planning-folder", "dist-folder"])
def test_install_update_stages_the_tag_and_hands_it_to_the_helper(tmp_path, monkeypatch, prefix):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    handed = []
    monkeypatch.setattr(updater, "_run_update_script", lambda path, flags, elevated: handed.append(Path(path).read_text(encoding="utf-8")))
    install = make_install(tmp_path)
    (tmp_path / "src").mkdir()
    release = _release_with_markers(tmp_path / "src", b"1.0.0\n", b"1.0.0\n")
    archive = _zip_of(release, tmp_path / "Planning.zip", prefix)
    updater.install_update(archive, install, "7.8.9")
    assert len(handed) == 1
    script = handed[0]
    assert re.search(r"\$versionValue = '7\.8\.9'", script)
    source = Path(re.search(r"\$source = '([^']+)'", script).group(1))
    assert (source / "version.txt").read_bytes() == b"7.8.9\n" and (source / "_internal" / "version.txt").read_bytes() == b"7.8.9\n"
    assert (install / "version.txt").read_text() == "1.0.2"                       # nothing of the installation was touched yet


# ------------------------------------------------------------------ 2+3. the real helper: the installed program reports the tag
def _as_installed_program(monkeypatch, install):
    """Make the updater read the version the way the packaged program does: from the install folder."""
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install / "Planning.exe"))


@needs_pwsh
def test_after_an_update_the_program_reports_the_tag_and_offers_only_newer_releases(tmp_path, monkeypatch):
    install = make_install(tmp_path)
    release = _release_with_markers(tmp_path, b"1.0.0\n", b"1.0.0\n")             # the ZIP was built while version.txt said 1.0.0
    updater._check_package_is_complete(release, "3.1.4")                           # what install_update does before the helper
    run = Run(tmp_path, release, install, new_version="3.1.4").go()
    assert run.launches == 1 and "Rolled back" not in run.log
    assert (install / "version.txt").read_bytes() == b"3.1.4\n"                    # UTF-8 without BOM, one LF
    assert (install / "_internal" / "version.txt").read_bytes() == b"3.1.4\n"
    assert "version.txt now says 3.1.4" in run.log and "Update finished" in run.log and "Update helper started: version 3.1.4" in run.log
    _as_installed_program(monkeypatch, install)
    assert updater.version_file_path() == install / "version.txt"
    assert updater.get_installed_version() == "3.1.4"
    for offered, expected in (("3.1.4", False), ("3.1.3", False), ("3.1.5", True), ("3.2.0", True), ("10.0.0", True), ("v3.1.4", False)):
        assert updater.is_newer_version(offered, updater.get_installed_version()) is expected, offered


@needs_pwsh
def test_the_helper_writes_the_tag_even_when_the_staged_marker_is_stale(tmp_path):
    """The second line of defence: the staged marker is wrong (check skipped) -- the helper still ends with the tag."""
    install = make_install(tmp_path)
    release = _release_with_markers(tmp_path, b"1.0.0\n", None)
    run = Run(tmp_path, release, install, new_version="4.0.1").go()
    assert run.launches == 1
    assert (install / "version.txt").read_bytes() == b"4.0.1\n"


@needs_pwsh
def test_two_updates_in_a_row_each_end_with_their_own_tag(tmp_path, monkeypatch):
    install = make_install(tmp_path)
    for tag in ("3.1.4", "3.1.9"):
        release = _release_with_markers(tmp_path, b"1.0.0\n", b"1.0.0\n")
        updater._check_package_is_complete(release, tag)
        Run(tmp_path, release, install, new_version=tag).go()
        _as_installed_program(monkeypatch, install)
        assert updater.get_installed_version() == tag
        assert updater.is_newer_version(tag, updater.get_installed_version()) is False
    assert updater.is_newer_version("3.1.10", updater.get_installed_version()) is True      # 3.1.10 is newer than 3.1.9 (numbers, not text)


# ------------------------------------------------------------------ 4. a failed update keeps the old version.txt
@needs_shell
def test_a_rolled_back_update_keeps_the_old_version_marker(tmp_path, monkeypatch):
    install = make_install(tmp_path)
    original = tree(install)
    release = _release_with_markers(tmp_path, b"1.0.0\n", b"1.0.0\n")
    updater._check_package_is_complete(release, "5.0.0")
    run = Run(tmp_path, release, install, mode="none", new_version="5.0.0").go()      # the new program never starts
    assert "never started running" in run.log
    assert tree(install) == original and (install / "version.txt").read_text() == "1.0.2"
    _as_installed_program(monkeypatch, install)
    assert updater.get_installed_version() == "1.0.2"


# ------------------------------------------------------------------ 3. reading the version
def test_the_external_marker_wins_over_the_internal_one(tmp_path, monkeypatch):
    install = tmp_path / "app"
    (install / "_internal").mkdir(parents=True)
    (install / "Planning.exe").write_bytes(b"x")
    (install / "_internal" / "version.txt").write_text("1.3.6\n")
    _as_installed_program(monkeypatch, install)
    assert updater.get_installed_version() == "1.3.6"                              # no external marker yet (a fresh build)
    (install / "version.txt").write_bytes(b"\xef\xbb\xbf1.3.7\r\n")
    assert updater.get_installed_version() == "1.3.7"                              # the tag written by an update wins


# ------------------------------------------------------------------ the release the updater looks at
class _Response:
    def __init__(self, payload):
        self._body = json.dumps(payload).encode("utf-8")

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def _latest(monkeypatch, tag, installed, assets=None):
    payload = {"tag_name": tag, "name": "Release", "body": "notes", "html_url": "https://example/rel",
               "assets": assets if assets is not None else [
                   {"name": "log.zip", "browser_download_url": "https://example/log.zip"},
                   {"name": "Planning.zip", "browser_download_url": "https://example/Planning.zip"}]}
    monkeypatch.setattr(updater, "urlopen", lambda request, timeout=0: _Response(payload))
    monkeypatch.setattr(updater, "get_installed_version", lambda: installed)
    return updater.fetch_latest_release()


def test_the_latest_release_tag_becomes_the_version_to_install(monkeypatch):
    release = _latest(monkeypatch, "v1.3.7", "1.3.6")
    assert (release.version, release.tag_name, release.installer_name) == ("1.3.7", "v1.3.7", "Planning.zip")
    assert release.installer_url == "https://example/Planning.zip"              # Planning.zip, not the other ZIP listed first


@pytest.mark.parametrize("installed", ["1.3.7", "1.3.8", "2.0.0"])
def test_a_release_that_is_not_newer_than_the_installed_version_is_not_offered(monkeypatch, installed):
    assert _latest(monkeypatch, "v1.3.7", installed) is None


def test_the_installer_asset_is_planning_zip_whatever_the_order_or_case(monkeypatch):
    assets = [{"name": "a-debug.zip", "browser_download_url": "u1"}, {"name": "PLANNING.ZIP", "browser_download_url": "u2"},
              {"name": "notes.txt", "browser_download_url": "u3"}]
    assert updater._choose_installer(assets) == ("PLANNING.ZIP", "u2")
    assert updater._choose_installer([{"name": "only.zip", "browser_download_url": "u"}]) == ("only.zip", "u")
    assert updater._choose_installer([{"name": "notes.txt", "browser_download_url": "u"}]) == ("", "")


# ------------------------------------------------------------------ the contract, pinned in the files that implement it
def test_build_bat_makes_the_one_zip_the_updater_wants_and_does_not_put_a_version_in_its_name():
    text = (ROOT / "build.bat").read_text(encoding="utf-8", errors="replace")
    assert "Compress-Archive -Path 'dist\\Planning\\*' -DestinationPath 'dist\\Planning.zip'" in text
    assert "ok='Planning.exe' in names and dll" in text and "_internal/python3" in text           # it refuses an incomplete ZIP itself
    assert "Planning_v" not in text                                                               # the version comes from the tag


def test_the_helper_writes_the_version_only_after_the_copy_was_verified_and_never_when_rolling_back():
    script = updater._UPDATE_SCRIPT_TEMPLATE
    verified = script.index("$problems = Find-MissingFiles $source $target")
    write = script.index("[System.IO.File]::WriteAllText($versionPath")
    assert verified < write < script.index("Start-Planning)) { throw")
    assert script.count("WriteAllText($versionPath") == 1                                          # one place: inside `if ($copied)`
    restore = script[script.index("function Restore-Backup"):script.index("function Start-Planning")]
    assert "version.txt" not in restore                                                            # a rollback restores the old marker with the old files


def test_the_release_steps_document_the_tag_rule():
    text = (ROOT / "docs" / "RELEASE_STEPS.md").read_text(encoding="utf-8")
    assert "tag" in text and "Planning.zip" in text and "build.bat" in text
