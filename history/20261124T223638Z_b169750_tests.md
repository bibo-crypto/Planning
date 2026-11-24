# tests — SUCCESS

- commit: `b169750` on `v1.3.12` — update(docs, CHANGED-FILES-vs-repository): 5 modified (+88/-15)
- run: https://github.com/bibo-crypto/Planning/actions/runs/45501686521
- event: push   |   report written: 2026-11-24 22:36 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| pytest (3.12) | success | - |
| pytest (3.14) | success | - |

## pytest — pytest-log-py3.12

`1067 passed, 12 skipped in 243.94s (0:04:03)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1683: The updater no longer spawns a PowerShell helper.`
- `SKIPPED [1] tests\test_regressions.py:1754: UAC elevation is now requested for the Setup installer.`
- `SKIPPED [1] tests\test_regressions.py:1584: The updater no longer generates PowerShell update scripts.`
- `SKIPPED [1] tests\test_regressions.py:1629: The Setup installer handles application replacement and restart.`
- `SKIPPED [1] tests\test_regressions.py:1575: The updater now launches the standard Setup installer.`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_regressions.py:1561: ZIP extraction was replaced by the standard Setup installer.`

## pytest — pytest-log-py3.14

`1067 passed, 12 skipped in 214.52s (0:03:34)`

Skipped (reason):

- `SKIPPED [1] tests\test_ci_report.py:131: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:138: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:149: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:160: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_ci_report.py:171: ci/publish_report.sh runs on the Ubuntu runner (needs bash and git)`
- `SKIPPED [1] tests\test_regressions.py:1683: The updater no longer spawns a PowerShell helper.`
- `SKIPPED [1] tests\test_regressions.py:1754: UAC elevation is now requested for the Setup installer.`
- `SKIPPED [1] tests\test_regressions.py:1584: The updater no longer generates PowerShell update scripts.`
- `SKIPPED [1] tests\test_regressions.py:1629: The Setup installer handles application replacement and restart.`
- `SKIPPED [1] tests\test_regressions.py:1575: The updater now launches the standard Setup installer.`
- `SKIPPED [1] tests\test_regressions.py:1452: win32com is available in this environment`
- `SKIPPED [1] tests\test_regressions.py:1561: ZIP extraction was replaced by the standard Setup installer.`
