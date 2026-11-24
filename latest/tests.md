# tests — FAILURE

- commit: `ec5a269` on `v1.3.11` — fix(updater): publish complete installer release
- run: https://github.com/bibo-crypto/Planning/actions/runs/45495194840
- event: push   |   report written: 2026-11-24 21:55 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.12) | failure | Run the test suite |
| pytest (3.14) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`8 failed, 1065 passed, 6 skipped in 212.50s (0:03:32)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_download_installer_rejects_corrupt_zip - AssertionError: 'corrupt' not found in 'the release does not contain a planning_setup windows installer.'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_download_installer_rejects_truncated_download - AssertionError: 'incomplete' not found in 'the release does not contain a planning_setup windows installer.'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_requires_frozen_app - ImportError: cannot import name 'install_update' from 'utility.updater' (D:\a\Planning\Planning\utility\updater.py)`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_safe_extract_blocks_zip_slip - ImportError: cannot import name '_safe_extract' from 'utility.updater' (D:\a\Planning\Planning\utility\updater.py)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`

## pytest — pytest-log-py3.14

`8 failed, 1065 passed, 6 skipped in 173.83s (0:02:53)`

Failed / errored:

- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_download_installer_rejects_corrupt_zip - AssertionError: 'corrupt' not found in 'the release does not contain a planning_setup windows installer.'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_download_installer_rejects_truncated_download - AssertionError: 'incomplete' not found in 'the release does not contain a planning_setup windows installer.'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_detaches_helper_from_any_job_object - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_elevates_when_install_dir_unwritable - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_generates_backup_and_rollback_script - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_relaunches_de_elevated - AttributeError: module 'utility.updater' has no attribute 'install_update'`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_install_update_requires_frozen_app - ImportError: cannot import name 'install_update' from 'utility.updater' (D:\a\Planning\Planning\utility\updater.py)`
- `FAILED tests/test_regressions.py::PlanningRegressionTests::test_safe_extract_blocks_zip_slip - ImportError: cannot import name '_safe_extract' from 'utility.updater' (D:\a\Planning\Planning\utility\updater.py)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
