# tests — FAILURE

- commit: `2271c2e` on `main` — fix(updater): verify updates by normalized SHA-256 manifests
- run: https://github.com/bibo-crypto/Planning/actions/runs/44902116830
- event: push   |   report written: 2026-11-21 12:10 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | failure | Run the test suite |
| pytest (3.12) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`4 failed, 972 passed, 9 skipped in 220.73s (0:03:40)`

Failed / errored:

- `FAILED tests/test_update_script.py::test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched - AssertionError: assert ('never started running' in '2026-11-21T12:09:15  Backup of the current version copied and verified.\r\n2026-11-21T12:09:15  Copy attempt 1: 1 fil...ts -- rolli`
- `FAILED tests/test_update_script.py::test_a_stage_folder_reached_through_its_short_8_3_name_is_verified_correctly - AssertionError: 2026-11-21T12:09:17  Backup of the current version copied and verified.`
- `FAILED tests/test_update_script.py::test_a_stage_folder_with_spaces_and_odd_spellings_is_verified_on_the_first_attempt - AssertionError: assert ('not in place yet' not in '2026-11-21T...rified).\r\n'`
- `FAILED tests/test_update_script.py::test_a_rolled_back_update_leaves_a_note_for_the_program - AssertionError: assert ('version=9.9.9' in 'version=9.9.9\ntime=2026-11-21T12:09:19\nlog=C:\\Users\\runneradmin\\AppData\\Local\\Temp\\pytest-of-runneradmin\\pyt... be copied completely: 1 file(s) of the ne`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:349: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`4 failed, 972 passed, 9 skipped in 254.29s (0:04:14)`

Failed / errored:

- `FAILED tests/test_update_script.py::test_a_new_version_that_never_starts_is_rolled_back_and_the_old_one_relaunched - AssertionError: assert ('never started running' in '2026-11-21T12:10:05  Backup of the current version copied and verified.\r\n2026-11-21T12:10:05  Copy attempt 1: 1 fil...ts -- rolli`
- `FAILED tests/test_update_script.py::test_a_stage_folder_reached_through_its_short_8_3_name_is_verified_correctly - AssertionError: 2026-11-21T12:10:07  Backup of the current version copied and verified.`
- `FAILED tests/test_update_script.py::test_a_stage_folder_with_spaces_and_odd_spellings_is_verified_on_the_first_attempt - AssertionError: assert ('not in place yet' not in '2026-11-21T...rified).\r\n'`
- `FAILED tests/test_update_script.py::test_a_rolled_back_update_leaves_a_note_for_the_program - AssertionError: assert ('version=9.9.9' in 'version=9.9.9\ntime=2026-11-21T12:10:09\nlog=C:\\Users\\runneradmin\\AppData\\Local\\Temp\\pytest-of-runneradmin\\pyt... be copied completely: 1 file(s) of the ne`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:349: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
