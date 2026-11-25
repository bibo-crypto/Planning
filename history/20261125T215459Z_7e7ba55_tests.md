# tests — FAILURE

- commit: `7e7ba55` on `main` — chore(release): bump version to 1.3.6
- run: https://github.com/bibo-crypto/Planning/actions/runs/45707894490
- event: push   |   report written: 2026-11-25 21:54 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.12) | failure | Run the test suite |
| pytest (3.14) | failure | Run the test suite |

## pytest — pytest-log-py3.12

`1 failed, 1103 passed, 10 skipped in 226.79s (0:03:46)`

Failed / errored:

- `FAILED tests/test_update_system.py::test_write_version_file_writes_the_plain_version_and_verifies_it - AssertionError: assert b'1.4.2\r\n' == b'1.4.2\n'`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_elvy_lot.py:135: no display`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_system.py:193: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_system.py:210: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_system.py:218: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`1 failed, 1104 passed, 9 skipped in 198.45s (0:03:18)`

Failed / errored:

- `FAILED tests/test_update_system.py::test_write_version_file_writes_the_plain_version_and_verifies_it - AssertionError: assert b'1.4.2\r\n' == b'1.4.2\n'`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_system.py:193: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_system.py:210: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_system.py:218: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
