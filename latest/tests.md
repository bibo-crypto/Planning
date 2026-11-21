# tests — FAILURE

- commit: `a3172dd` on `main` — chore(release): bump version to 1.3.3
- run: https://github.com/bibo-crypto/Planning/actions/runs/44956537173
- event: push   |   report written: 2026-11-21 22:29 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | failure | Run the test suite |
| pytest (3.12) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`4 failed, 979 passed, 9 skipped in 200.51s (0:03:20)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:390: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`4 failed, 979 passed, 9 skipped in 240.55s (0:04:00)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - RuntimeError: The update package is incomplete (the Python DLL is missing from _internal), so it was not installed.`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:390: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
