# windows-exe — SUCCESS

- commit: `ec5a269` on `v1.3.11` — fix(updater): publish complete installer release
- run: https://github.com/bibo-crypto/Planning/actions/runs/45495194932
- event: push   |   report written: 2026-11-24 21:53 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| build-and-smoke-test | success | - |

## pytest

No pytest.log artifact for this run.

## Packaged EXE smoke test

- result: **OK** — `Planning started` logged 2× (expected 2: empty profile, then restart)

```
2026-11-24 21:52:38  INFO      Planning v1.3.11 starting (data folder: D:\a\_temp\planning-smoke\LocalAppData\Planning)
2026-11-24 21:52:40  INFO      Startup timing: database 0.02 s | page imports 0.49 s | widgets 2.11 s | total 2.62 s
2026-11-24 21:52:40  INFO      Planning started: all pages built (v1.3.11)
2026-11-24 21:52:42  INFO      Planning v1.3.11 starting (data folder: D:\a\_temp\planning-smoke\LocalAppData\Planning)
2026-11-24 21:52:43  INFO      Startup timing: database 0.02 s | page imports 0.24 s | widgets 0.54 s | total 0.79 s
2026-11-24 21:52:43  INFO      Planning started: all pages built (v1.3.11)
```
