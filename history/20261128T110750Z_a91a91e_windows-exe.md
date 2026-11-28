# windows-exe — SUCCESS

- commit: `a91a91e` on `main` — test(updater): cover stale file cleanup and rollback sync
- run: https://github.com/bibo-crypto/Planning/actions/runs/46138174444
- event: push   |   report written: 2026-11-28 11:07 UTC

## Jobs

| job | result | failed steps |
|---|---|---|
| build-and-smoke-test | success | - |

## pytest

No pytest.log artifact for this run.

## Packaged EXE smoke test

- result: **OK** — `Planning started` logged 2× (expected 2: empty profile, then restart)

```
2026-11-28 11:07:21  INFO      Planning v1.3.11 starting (data folder: D:\a\_temp\planning-smoke\LocalAppData\Planning)
2026-11-28 11:07:23  INFO      Startup timing: database 0.02 s | page imports 0.25 s | widgets 1.85 s | total 2.12 s
2026-11-28 11:07:23  INFO      Planning started: all pages built (v1.3.11)
2026-11-28 11:07:25  INFO      Planning v1.3.11 starting (data folder: D:\a\_temp\planning-smoke\LocalAppData\Planning)
2026-11-28 11:07:26  INFO      Startup timing: database 0.03 s | page imports 0.28 s | widgets 0.64 s | total 0.95 s
2026-11-28 11:07:26  INFO      Planning started: all pages built (v1.3.11)
```
