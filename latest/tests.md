# tests — SUCCESS

- commit: `65ff9f4` on `main` — feat(updater, backup, sqlite-retry): 4 added, 213 modified (+636/-110)
- run: https://github.com/bibo-crypto/Planning/actions/runs/44831704483
- event: push   |   report written: 2026-11-20 22:52 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.14) | success | - |
| pytest (3.12) | success | - |

## pytest — pytest-log-py3.12

`974 passed, 10 skipped in 215.86s (0:03:35)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_create_pages.py:209: no display`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:319: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`

## pytest — pytest-log-py3.14

`975 passed, 9 skipped in 245.31s (0:04:05)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_update_script.py:120: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
- `SKIPPED [1] tests\test_update_script.py:149: needs an unprivileged user: permissions do not bind root (verified by hand with runuser)`
- `SKIPPED [1] tests\test_update_script.py:319: starts a real helper process (a renamed `sleep`): runs on Linux/macOS with pwsh`
