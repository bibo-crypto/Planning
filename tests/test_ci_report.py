"""ci/make_report.py and ci/publish_report.sh: the CI report that is published to the ``ci-reports`` branch."""
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location("make_report", ROOT / "ci" / "make_report.py")
make_report = importlib.util.module_from_spec(spec)
spec.loader.exec_module(make_report)

GREEN = "....\r\n=== warnings summary ===\r\nsome warning\r\n\r\n-- Docs: https://docs.pytest.org\r\n666 passed, 2 skipped, 1 warning in 135.43s (0:02:15)\r\n"
FAILING = ("...F\r\nFAILED tests/test_a.py::test_x - assert 1 == 2\r\nERROR tests/test_b.py::test_y - boom\r\n"
           "SKIPPED [1] tests\\test_c.py:49: screen is 1024 px wide, this test needs 1920 px\r\n"
           "1 failed, 1 error, 600 passed, 1 skipped in 10.00s\r\n")
META = {"workflowName": "tests", "conclusion": "failure", "headSha": "e1ab404abcdef", "headBranch": "main",
        "displayTitle": "update(x)", "url": "https://github.com/o/r/actions/runs/1", "event": "push",
        "jobs": [{"name": "pytest (3.12)", "conclusion": "failure",
                  "steps": [{"name": "Run the test suite", "conclusion": "failure"}, {"name": "Annotate", "conclusion": "success"}]}]}
EXE_OK = ("2026-11-13 15:16:13  INFO      Planning v1.0.2 starting (data folder: x)\n"
          "2026-11-13 15:16:15  INFO      Planning started: all pages built (v1.0.2)\n" * 2)


def artifacts(tmp_path, pytest_text=None, exe_text=None, hang=False):
    root = tmp_path / "artifacts"
    if pytest_text is not None:
        (root / "pytest-log-py3.12").mkdir(parents=True)
        (root / "pytest-log-py3.12" / "pytest.log").write_text(pytest_text, encoding="utf-8")
    if exe_text is not None:
        folder = root / "exe-smoke-logs" / "LocalAppData" / "Planning" / "logs"
        folder.mkdir(parents=True)
        (folder / "converter.log").write_text(exe_text, encoding="utf-8")
        if hang:
            (folder / "startup_hang.log").write_text("stuck", encoding="utf-8")
    root.mkdir(exist_ok=True)
    return root


# ------------------------------------------------------------------ parsing
def test_a_green_log_has_counts_and_nothing_failed():
    result = make_report.parse_pytest_log(GREEN)
    assert result["counts"] == {"passed": 666, "skipped": 2, "warning": 1}
    assert result["failed"] == [] and result["summary"].startswith("666 passed")


def test_failed_errored_and_skipped_tests_are_listed_with_the_reason():
    result = make_report.parse_pytest_log(FAILING)
    assert result["counts"]["failed"] == 1 and result["counts"]["error"] == 1 and result["counts"]["passed"] == 600
    assert [line.split(" - ")[0] for line in result["failed"]] == ["FAILED tests/test_a.py::test_x", "ERROR tests/test_b.py::test_y"]
    assert "screen is 1024 px wide" in result["skipped"][0]


def test_a_log_without_a_summary_is_reported_as_such_not_as_green():
    result = make_report.parse_pytest_log("Traceback: interpreter crashed\r\n")
    assert result["summary"] == "no pytest summary line found" and result["counts"] == {}


# ------------------------------------------------------------------ the report
def test_the_report_names_the_failing_test_the_skip_reason_and_the_failed_step(tmp_path):
    markdown, data = make_report.build_report(artifacts(tmp_path, FAILING), META)
    assert "# tests — FAILURE" in markdown and "`e1ab404`" in markdown
    assert "| pytest (3.12) | failure | Run the test suite |" in markdown
    assert "FAILED tests/test_a.py::test_x" in markdown and "this test needs 1920 px" in markdown
    assert data["failed_tests"][0].startswith("pytest-log-py3.12: FAILED tests/test_a.py::test_x")
    assert data["pytest"]["pytest-log-py3.12"]["counts"]["failed"] == 1 and data["exe_smoke"] is None


def test_the_exe_smoke_is_ok_only_when_both_starts_are_logged_and_nothing_hung(tmp_path):
    ok = make_report.build_report(artifacts(tmp_path / "a", GREEN, EXE_OK), META)[1]["exe_smoke"]
    assert ok == {"ok": True, "started_count": 2, "hang_files": []}

    one_start = EXE_OK.split("\n")[0] + "\n" + EXE_OK.split("\n")[1] + "\n"
    assert make_report.build_report(artifacts(tmp_path / "b", GREEN, one_start), META)[1]["exe_smoke"]["ok"] is False
    assert make_report.build_report(artifacts(tmp_path / "c", GREEN, EXE_OK, hang=True), META)[1]["exe_smoke"]["ok"] is False
    with_error = EXE_OK + "2026-11-13 15:16:20  ERROR     Planning could not build its pages\n"
    assert make_report.build_report(artifacts(tmp_path / "d", GREEN, with_error), META)[1]["exe_smoke"]["ok"] is False


def test_a_run_without_artifacts_still_gets_a_report(tmp_path):
    markdown, data = make_report.build_report(artifacts(tmp_path), META)
    assert "No pytest.log artifact" in markdown and data["pytest"] == {}


def test_main_writes_latest_and_history_files(tmp_path):
    meta = tmp_path / "meta.json"
    meta.write_text(json.dumps(META), encoding="utf-8")
    out = tmp_path / "report"
    done = subprocess.run([sys.executable, str(ROOT / "ci" / "make_report.py"), "--artifacts", str(artifacts(tmp_path, GREEN)),
                           "--meta", str(meta), "--out-dir", str(out)], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert (out / "latest" / "tests.md").is_file() and json.loads((out / "latest" / "tests.json").read_text())["sha"] == "e1ab404"
    assert len(list((out / "history").glob("*_e1ab404_tests.md"))) == 1


# ------------------------------------------------------------------ publishing (runs on the Ubuntu runner)
needs_unix = pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash") or not shutil.which("git"),
                                reason="ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)")


def report_dir(tmp_path, name, workflow="tests", sha="aaaaaaa", stamp="20261114T000000Z", text="x"):
    folder = tmp_path / name
    (folder / "latest").mkdir(parents=True)
    (folder / "history").mkdir()
    (folder / "latest" / f"{workflow}.md").write_text(text, encoding="utf-8")
    (folder / "history" / f"{stamp}_{sha}_{workflow}.md").write_text(text, encoding="utf-8")
    return folder


def publish(remote, folder, label="t", **env):
    import os
    return subprocess.run(["bash", str(ROOT / "ci" / "publish_report.sh"), str(remote), str(folder), label],
                          capture_output=True, text=True, env={**os.environ, **env})


def branch_files(remote):
    done = subprocess.run(["git", "-C", str(remote), "ls-tree", "-r", "--name-only", "ci-reports"], capture_output=True, text=True)
    return done.stdout.split()


@pytest.fixture
def remote(tmp_path):
    path = tmp_path / "remote.git"
    subprocess.run(["git", "init", "--quiet", "--bare", str(path)], check=True)
    return path


@needs_unix
def test_the_first_publish_creates_the_branch_with_only_report_files(tmp_path, remote):
    done = publish(remote, report_dir(tmp_path, "r1"))
    assert done.returncode == 0, done.stderr
    assert sorted(branch_files(remote)) == ["README.md", "history/20261114T000000Z_aaaaaaa_tests.md", "latest/tests.md"]


@needs_unix
def test_two_workflows_share_the_branch_and_an_unchanged_report_is_not_published_twice(tmp_path, remote):
    assert publish(remote, report_dir(tmp_path, "r1")).returncode == 0
    assert publish(remote, report_dir(tmp_path, "r2", workflow="windows-exe", stamp="20261114T000100Z")).returncode == 0
    assert {"latest/tests.md", "latest/windows-exe.md"} <= set(branch_files(remote))
    before = subprocess.run(["git", "-C", str(remote), "rev-list", "--count", "ci-reports"], capture_output=True, text=True).stdout
    assert "nothing new" in publish(remote, report_dir(tmp_path, "r1b")).stdout
    after = subprocess.run(["git", "-C", str(remote), "rev-list", "--count", "ci-reports"], capture_output=True, text=True).stdout
    assert before == after


@needs_unix
def test_history_is_limited_to_the_newest_files_and_latest_is_kept(tmp_path, remote):
    for index in range(1, 6):
        folder = report_dir(tmp_path, f"r{index}", stamp=f"2026111{index}T000000Z", text=f"run {index}")
        assert publish(remote, folder, CI_REPORTS_KEEP="3").returncode == 0
    history = sorted(name for name in branch_files(remote) if name.startswith("history/"))
    assert [name.split("/")[1][:9] for name in history] == ["20261113T", "20261114T", "20261115T"]
    shown = subprocess.run(["git", "-C", str(remote), "show", "ci-reports:latest/tests.md"], capture_output=True, text=True).stdout
    assert shown == "run 5"
