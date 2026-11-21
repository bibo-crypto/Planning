# tests — FAILURE

- commit: `ee8665e` on `main` — fix(updater): canonicalize staged version metadata
- run: https://github.com/bibo-crypto/Planning/actions/runs/44912317664
- event: push   |   report written: 2026-11-21 14:13 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | failure | Run the test suite |
| pytest (3.12) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`4 failed, 978 passed, 9 skipped in 227.94s (0:03:47)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - RuntimeError: The update ZIP must contain version.txt.`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:376: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`4 failed, 978 passed, 9 skipped in 192.21s (0:03:12)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - RuntimeError: The update ZIP must contain version.txt.`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - RuntimeError: The update ZIP must contain version.txt.`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:376: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
