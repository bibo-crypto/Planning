"""tools/check_release_zip.py reports what the in-app updater would refuse (the incident: a release ZIP holding only Planning.exe)."""
import sys
import zipfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))
import check_release_zip as tool                                    # noqa: E402


@pytest.fixture(autouse=True)
def small_is_fine(monkeypatch):
    monkeypatch.setattr(tool, "MIN_PLAUSIBLE_BYTES", 0)             # the synthetic packages are tiny


def make(tmp_path, entries, name="release.zip"):
    path = tmp_path / name
    with zipfile.ZipFile(path, "w") as z:
        for entry, content in entries.items():
            z.writestr(entry, content)
    return path


GOOD = {"Planning.exe": b"exe", "_internal/python314.dll": b"dll", "_internal/base_library.zip": b"x"}


def test_a_complete_package_is_accepted(tmp_path):
    assert tool.check_zip(make(tmp_path, GOOD), "v1.3.6") == []


def test_the_exe_only_release_zip_of_the_incident_is_refused(tmp_path):
    problems = tool.check_zip(make(tmp_path, {"Planning.exe": b"x" * 100}), "v1.3.5")
    assert any("python3*.dll is missing" in p and "build.bat" in p for p in problems)
    assert len(problems) >= 1


def test_the_archive_is_independent_of_the_release_tag(tmp_path):
    assert tool.check_zip(make(tmp_path, GOOD), "v9.9.9") == []


def test_a_package_without_base_library_is_refused(tmp_path):
    incomplete = {"Planning.exe": b"exe", "_internal/python314.dll": b"dll"}
    problems = tool.check_zip(make(tmp_path, incomplete), "v1.3.9")
    assert any("base_library.zip" in problem for problem in problems)


def test_an_archive_without_a_version_marker_is_accepted(tmp_path):
    assert tool.check_zip(make(tmp_path, GOOD), "1.3.6") == []


def test_a_package_inside_one_top_folder_is_accepted(tmp_path):
    assert tool.check_zip(make(tmp_path, {f"Planning/{k}": v for k, v in GOOD.items()}), "v1.3.6") == []


def test_no_exe_and_not_a_zip_are_reported(tmp_path):
    assert any("Planning.exe is not at the top" in p for p in tool.check_zip(make(tmp_path, {"readme.txt": b"x"})))
    broken = tmp_path / "broken.zip"
    broken.write_bytes(b"not a zip")
    assert any("not a readable ZIP" in p for p in tool.check_zip(broken))


def test_a_zip_far_too_small_for_a_whole_program_is_reported(tmp_path, monkeypatch):
    monkeypatch.setattr(tool, "MIN_PLAUSIBLE_BYTES", 10 ** 9)
    assert any("unpacks to only" in p for p in tool.check_zip(make(tmp_path, GOOD), "v1.3.6"))


def test_main_returns_the_exit_code(tmp_path, capsys):
    assert tool.main([str(make(tmp_path, GOOD)), "--tag", "v1.3.6"]) == 0
    assert tool.main([str(make(tmp_path, {"Planning.exe": b"x"}, "bad.zip"))]) == 1
    assert "REFUSE" in capsys.readouterr().out
