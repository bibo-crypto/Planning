# Planning — Engineering Review and Release Preparation

Review date: 2026-11-16. Basis: the project as pushed in commit `8cb47a1` (main) plus the changes listed in section 3.
Nothing in this review was pushed or merged: the result is a complete project folder for testing on a Windows machine first.

## Merge round (2026-11-22): the repository (1.3.3) + the round-2 fixes + speed

Base: the repository at `a3172dd`. Version stays 1.3.3 (choosing a new version is a release decision).

**Why the 4 failing tests failed, and the fix.** `test_regressions.py::test_install_update_*` built fake update ZIPs containing only
`Planning.exe`. Since `fdf2934` the updater (deliberately: the published v1.3.2 ZIP held only `Planning.exe`) refuses a package without
`_internal/python3*.dll`, so those four tests hit that refusal. The updater is right; the four fixtures now add a fake
`Planning/_internal/python312.dll`. `tests/test_update_script.py` still proves an exe-only package is refused.

**Kept from the repository:** the whole updater (SHA-256 manifests, canonical `version.txt`, expected version), version 1.3.3 files,
the `build.bat` ZIP-content check, `docs/RELEASE_DEPENDENCIES.md`, `constraints-release.txt`, lint cleanups, `sqlite_retry.py`
(`connect_with_retry` / `run_with_sqlite_retry`) and `situazione_db.get_conn`.

**Taken from the round-2 work (each has a test):**
* `orders_db` / `prezzi_db`: creating the table is inside the retry and a half-open connection is closed. The repository had added
  `PRAGMA busy_timeout=5000` after `timeout=10` (waiting for a lock dropped from 10 s to 5 s) and made `prezzi_db` return `sqlite3.Row`;
  both were **not** kept (no reason stated; `prezzi_db` reads rows by index only).
* `restore_backup`: all-or-nothing, the database's `-wal`/`-shm` files are put back too, no leftover temporary files.
* `post_to_ui(retry_for=)`: not retried after the UI was destroyed. Window: **`RESULT_RETRY_SECONDS = 10.0`** (shorter, as requested).
  A result that is not deliverable within 10 s (a modal dialog open longer) is dropped and its "running" flag released, as before.
* Auto-Assign after a failure re-reads the workbook on the worker thread, only if a row was saved.
* `partita_sort_key`: `nan` and `inf` sort as text. `exc_info=True` on 45 handlers. Tests: Tk helper, SQLite open retry (38),
  restore (5), tracebacks (4), constraints. The repository's weaker assertions in the flag-release tests were replaced by the exact ones.
* Not touched, flagged for the owner: `kamal_tab` now loads the C170 DFM cache (`KAMAL_ARTICLE_PREFIX`) instead of the default prefix.

**Speed (measured, same output).** The cost was openpyxl hashing a style object for every cell (`cell.alignment = ...`):

| Operation | Before | After |
|---|---|---|
| Shared workbook, 1500 rows: add rows / edit a row / save PG-X partita | 10.4 s / 15.9 s / 16.2 s | 1.8 s / 1.8 s / 2.4 s |
| `style_sheet` on a loaded 400-row sheet | 0.27 s | 0.006 s |
| PDF-to-Excel export (`write_data`), 300 rows | 0.08 s | 0.02 s (600 rows: about 6.7 s under the profiler before) |

(`style_sheet` is also used by the Ordine MED, Prezzi and Biglietti exports.) The files are the same: cell by cell comparison in
`tests/test_style_sheet_equivalence.py` and `tests/test_excel_exporter_fast_styles.py`; `styles.xml` differs only in the numbering of
two custom number formats. Startup was measured too: importing the GUI takes 0.07 s and building all pages 0.04 s on Linux with an
empty profile (pandas/openpyxl load in the background), so no startup change was made. **Not measured:** the real Situazione/PDF
workloads of the user's data and the packaged EXE on Windows.

**What the user's `converter.log` (1287 lines, up to 2026-11-22) shows.**
* Start-up: 26 starts, "Planning vX starting" -> "all pages built" took **4-11 s, average 7.5 s**, in every version. The window builds all
  pages on the main thread and nearly all of that is importing pandas/numpy and openpyxl/lxml/Pillow one after the other.
  New `utility/warmup.py` (called first thing in `main()`): two background threads import `numpy, pandas` and `lxml.etree, openpyxl` while the
  window is built; the main thread still runs the same `import` lines and finds them done (or waits for the thread - import locks make it
  safe); any error is swallowed so the normal import reports it as before; `PLANNING_NO_WARMUP=1` switches it off. **Benefit NOT measured:**
  this sandbox has one CPU core (0.78 s without vs 0.75 s with, i.e. no harm), so the overlap can only be confirmed on the user's PC - compare the
  "starting" -> "all pages built" times in the next log.
* `disk I/O error` (5 times: 19 Oct restore at start-up, 19 Oct DFM snapshot, 12 Nov copertura cache, 13 Nov, 14 Nov in `snapshot_fingerprint`
  -> `get_conn`) - the same signature the retry in `get_conn` / `orders_db` / `prezzi_db` now covers while opening. Only the 14 Nov one has a
  traceback (those handlers had none: `exc_info` was added), so the exact statement of the others is unknown.
* Versions in the log: `1.2.5 -> 1.2.6 -> 1.2.7 -> 1.0.2 (21 Nov) -> 1.3.0 -> 1.3.3`. The 1.0.2 build is a downgrade (a build whose `version.txt` said 1.0.2).
  Up to 1.2.7 the version text carries an invisible BOM character (`v<U+FEFF>1.2.7`, 28 lines) - the repository's canonical `version.txt` fixes that.
  The updater's own log (`%TEMP%\Planning_Update.log`) is NOT in `converter.log`, so why a given update failed cannot be read from this file.
* Kamal: confirmed by the owner that Kamal's colour articles start with C170, so the repository's `KAMAL_ARTICLE_PREFIX` change is right and kept.

**Tests (executed, Linux, virtual display, PowerShell 7.4.6):** Python 3.12.3 **1072 passed, 2 skipped**; Python 3.14.10 **1072 passed,
2 skipped**. Skipped: 8.3 short-path test (Windows only) and the non-root permission test. Windows: **not verified** (no Windows here).

## Release preparation 1.3.3 (2026-11-22)

* Version metadata is synchronized at 1.3.3 in `version.txt`, `installer.iss`, and `utility/updater.py`.
* The published v1.3.2 `Planning.zip` was verified to contain only `Planning.exe`; the source at that tag still says 1.3.0 in `version.txt`.
* Targeted release/updater tests: 6 passed. Ruff and Python compilation checks passed.
* PyInstaller build succeeded on Windows. The 1.3.3 ZIP contains 2,741 entries, `_internal/version.txt` (1.3.3), and `_internal/python314.dll`; no database files are included.
* The packaged executable passed both empty-profile and saved-profile restart smoke tests. A real in-place update from GitHub remains unverified; this ZIP has not been uploaded.

## Release preparation 1.2.9 (2026-11-21)

* Version metadata is synchronized at 1.2.9 in `version.txt`, `installer.iss`, and `utility/updater.py`.
* Targeted checks: `18 passed, 3 skipped` across `tests/test_version_consistency.py` and `tests/test_update_script.py`; Ruff and Python compilation checks passed.
* Windows PyInstaller build succeeded; the packaged `version.txt` contains 1.2.9. The packaged executable passed the empty-profile/restart smoke test.
* A real in-place update on the user's installed copy has **not** been verified. These build and smoke checks do not prove that the updater replaces files successfully on that machine.

> The review results below are historical: items marked **executed** have evidence in `test_reports/`, and items marked **NOT VERIFIED**
> could not be run in that review environment (Linux). The latest 1.3.3 checks are listed above; real in-place update verification remains outstanding.

## Update 2026-11-20

The previous update-script diagnosis uncovered a real short-path/8.3 defect: PowerShell 5.1 could return an 8.3 temporary path while
`Get-ChildItem.FullName` returned the long path, making prefix subtraction produce keys such as `bj\planning.exe`. The relative
file names are now derived from path items, and the Windows verifier keeps pytest's basetemp outside the repository. This Linux
review cannot prove the real 8.3 or real-update behavior; Windows verification remains required.

The latest Windows evidence reported by the user was `955 passed, 2 failed, 12 skipped`. The two failures were caused by pytest's
basetemp being inside `E:\Planning`, not by application code, and are addressed by the basetemp isolation and Tk retry changes.
SQLite opening/PRAGMA access now retries known transient lock/I/O errors; backup restore is staged and rolled back atomically;
Auto-Assign refreshes the workbook after a partial failure and retries UI delivery while a modal can block the main loop; the
history sync now logs a traceback; `nan` is sorted as text; and release dependency constraints are documented.

## Executed verification

* Python 3.14.3 Windows: `974 passed, 10 skipped, 0 failed`.
* Python 3.12 Windows: `972 passed, 12 skipped, 0 failed`.
* JUnit reports: `test_reports/junit-3.14.xml`, `test_reports/junit-3.12.xml`.
* Real 8.3 short-name and Windows PowerShell 5.1/real-update verification remain NOT VERIFIED here.
* A release constraints file was added: `constraints-release.txt`; the PRAGMA `user_version` migration gate remains deferred
  because existing idempotent column/schema checks are the project's established migration mechanism and no current defect requires it.

## 1. Executive summary

* **A critical defect was found in the in-app updater and fixed.** The PowerShell helper that replaces the installed files wiped the
  healthy installation and "restored" a partial copy whenever its own backup step failed (a locked file, no permission to create the
  backup folder, a full disk). The program then stopped with `Failed to load Python DLL '...\_internal\python312.dll'` — the error
  seen on the test machine. Reproduced with the real script (install folder left **empty**), fixed (install left **intact**),
  and covered by tests that run the script under PowerShell. See 4.1.
* A backup holding a damaged SQLite database could overwrite a healthy one on restore: fixed (checked before anything is replaced).
* Five operations of the shared-orders pages stayed marked "running" for ever when their result could not be delivered to the window,
  silently ignoring every later click: fixed. Seven direct Tk calls made from worker threads: fixed and now enforced by a test.
* The Smart Auto-Assign algorithm (matching PG-X rows to Magazino stock) had no test and lived inside a GUI method: moved unchanged to a
  Tk-free module and proven identical to the original on 600 random cases, plus business-rule tests.
* **Tests (Linux, Python 3.12 and 3.14): 968 passed, 0 failed, 1 skipped, 0 warnings on each.** Windows CI at commit `8cb47a1`:
  869 passed, 6 skipped per Python version; the Windows EXE build and its start/restart smoke test succeeded (section 6).
* Not done and not claimed: running the new code on Windows, and a real update of an installed copy (section 10).

## 2. Environment and what was executed

| Item | Value |
|---|---|
| Python | 3.12.3 and 3.14.10 (pandas 2.3.3, numpy 2.4.6) |
| OS | Linux (Ubuntu 24.04) with a virtual display 1920x1080; PowerShell 7.4.6 for the updater tests |
| Windows | **not available** to the reviewer; Windows evidence comes from the project's own GitHub Actions (section 6) |
| Packaging | PyInstaller 6.22 with the project's `main.spec` on Linux (section 7) |

## 3. Changes

**Modified** (production code): `utility/updater.py` (script rewritten, package check), `utility/backup.py` (restore checks databases first),
`utility/ui_thread.py` (`post_to_ui(..., on_dropped=)`), `gui/tabs/shared_order_actions.py` (flags released; auto-assign moved out),
`gui/tabs/shared_order_logic.py` (auto-assign algorithm added), `gui/tabs/kamal_tab.py`, `gui/tabs/ordine_med_tab.py` (Tk variables read on the UI thread),
`gui/tabs/overview_tab.py` (no `winfo_exists()` in a worker).
**Modified** (documents/tests): `REVIEW_REPORT.md` (replaced), `PERFORMANCE_REPORT.md` (marked historical), `REFACTORING_PLAN.md`, `ARCHITECTURE.md`,
`tests/test_elvy_prezzi_names.py`, `tests/test_failures_are_logged.py` (closed files; assertions unchanged).
**New:** `tools/verify_windows.ps1`; `docs/history/REVIEW_REPORT_1.1.11_historical.md`; tests `test_update_script.py`, `test_sqlite_reliability.py`
(+ `tests/fixtures/legacy_database_schemas.json`), `test_shared_workbook_scenarios.py`, `test_upload_gg_scenarios.py`, `test_auto_assign_suggestions.py`,
`test_auto_assign_apply.py`, `test_background_flags_released.py`, `test_thread_safety_rules.py`.
**Deleted:** nothing. No test was removed, weakened, skipped or marked xfail to pass.
The business logic (calculations, Excel formats, database schemas) was not changed.

## 4. Problems found, fixed, and how each was proven

### 4.1 Updater: a failed backup destroyed the installation — CRITICAL, fixed
* **Cause:** in the helper script, a failure of the backup copy went to the `catch` block, which ran `Restore-Backup`: delete everything in the
  install folder, then copy back whatever the (incomplete) backup contained, ignoring errors. The "copy succeeded" test was only
  `Test-Path Planning.exe`, which is always true because the old file is still there.
* **Reproduction (executed, real script, PowerShell 7):** the folder for `Planning_Backup` could not be created. Old script: install folder **empty**
  (`Planning.exe` and `python312.dll` gone). New script: install folder identical to the original. Second reproduction: one unreadable file
  during the backup — old script removed `Planning.exe` and `version.txt`. Evidence: `test_reports/update_script_before_after.txt`.
* **Fix:** (1) the backup is verified file by file against a list recorded before anything changes; (2) a rollback only happens when that backup
  is verified, otherwise the install is left untouched and the old program is started again; (3) the rollback is verified against the same
  list and nothing is deleted if it cannot be proven complete; (4) the update counts as copied only when every file of the new version is
  in place; (5) the package is refused before anything is touched if `_internal` has no `python3*.dll`.
* **Tests (executed):** `tests/test_update_script.py` renders the script exactly as the updater does and runs it with PowerShell: good update (all files,
  verified backup, cleanup), backup impossible, unreadable file, copy that never succeeds, new version that never starts, rollback that cannot be completed,
  incomplete package refused. Each compares the install folder byte for byte. Four of them also run on Windows PowerShell 5.1 when the suite runs on Windows.

### 4.2 Restore accepted a damaged database — HIGH, fixed
`restore_backup` replaced the live database with whatever the ZIP held. A backup taken from an already damaged database (the backup falls back to a raw copy
when the SQLite snapshot fails) would overwrite a healthy one. Now every database in the backup passes `PRAGMA integrity_check` (read-only) **before** the
first file is replaced; otherwise the restore is refused with a clear message and nothing changes. Test written first and failed (`DID NOT RAISE`), passes now.

### 4.3 Tk access from worker threads — MEDIUM, fixed and enforced
Found by scanning every `threading.Thread` target in `gui/`: `BooleanVar.get()` ×4 (Ordine MED, Ordine Kamal), `winfo_exists()` (Overview export) and two direct
`widget.after()` calls (PG-X upload). Tkinter refuses `after()` from a worker while the main thread is not in `mainloop` (for example inside a modal dialog).
Values are now read on the UI thread before the worker starts (the project's own pattern). `tests/test_thread_safety_rules.py` fails if any worker touches Tk again.

### 4.4 Operations blocked for ever when a result is dropped — MEDIUM/HIGH, fixed
PG-X save, PG-X editor save, move/delete rows, delete shipped colours and the Partita GG upload set a "running" flag cleared by a callback on the UI thread.
When that callback could not be scheduled the flag stayed set and every later click did nothing, silently. `post_to_ui` gained `on_dropped`; all 14 call sites
release their flag. Each of the five operations has a test that drops the first result and checks that the next click works (all five failed before the fix).

### 4.5 Smart Auto-Assign was untested — fixed (tested and extracted, behaviour unchanged)
The algorithm was moved to `gui/tabs/shared_order_logic.build_auto_assign_suggestions`. A verbatim copy of the original is kept in the test and compared on 600 random
cases (more than 300 matches), then 12 business rules (smallest sufficient batch, rocche already promised, lotto priority, fallback to the raw article, ...)
and the saving step (4 scenarios with a real thread and workbook).

### 4.6 Earlier in this review cycle (already delivered and pushed)
Startup failures are reported (no more silent "Loading application pages"); `init_db` no longer hides real migration errors and retries transient lock/I-O
errors; the notification store never overwrites an unreadable file and the price refresh can no longer save the result of a half-failed check; "Mark Resolved"
asks when the problem is still reported; the CI report branch `ci-reports` (verified live, section 8); 35 silent `except Exception` now log, and a test blocks new ones.

## 5. Test results (executed)

**Python 3.12.3** (Linux, virtual display 1920x1080, PowerShell 7.4.6 present)

| Test group | Passed | Failed | Skipped | Warnings | Total |
|---|---:|---:|---:|---:|---:|
| Shared Orders: window, logic, workbook, upload, auto-assign, background flags, thread rules | 209 | 0 | 0 | 0 | 209 |
| SQLite, notifications, backup, data integrity | 114 | 0 | 0 | 0 | 114 |
| Updater (real PowerShell script) and CI report | 19 | 0 | 1 | 0 | 20 |
| Application startup and GUI pages | 51 | 0 | 0 | 0 | 51 |
| Business logic, parsers, exporters, pipelines and the rest | 575 | 0 | 0 | 0 | 575 |
| **Total** | **968** | **0** | **1** | **0** | **969** |

**Python 3.14.10** (Linux, virtual display 1920x1080, PowerShell 7.4.6 present)

| Test group | Passed | Failed | Skipped | Warnings | Total |
|---|---:|---:|---:|---:|---:|
| Shared Orders: window, logic, workbook, upload, auto-assign, background flags, thread rules | 209 | 0 | 0 | 0 | 209 |
| SQLite, notifications, backup, data integrity | 114 | 0 | 0 | 0 | 114 |
| Updater (real PowerShell script) and CI report | 19 | 0 | 1 | 0 | 20 |
| Application startup and GUI pages | 51 | 0 | 0 | 0 | 51 |
| Business logic, parsers, exporters, pipelines and the rest | 575 | 0 | 0 | 0 | 575 |
| **Total** | **968** | **0** | **1** | **0** | **969** |

Skipped (1, both versions): `test_a_file_that_cannot_be_read_while_backing_up_cancels_the_update` — permissions do not bind root; the same situation was run by hand
as an unprivileged user (`update_script_before_after.txt`). Warnings: 0 with the project's normal settings; the suite also passes with `-W error::ResourceWarning`
on the files changed here.

Line coverage **76.1%**, branch coverage **56.6%** (was 71.0% / 51.5% at the start of this review). Modules touched by this review:

| Module | Line | Branch |
|---|---:|---:|
| `calculate/prezzi.py` | 89.4% | 81.2% |
| `exporters/biglietti/shared_workbook.py` | 87.9% | 75.7% |
| `gui/notifications_window.py` | 96.8% | 96.2% |
| `gui/tabs/shared_order_actions.py` | 62.0% | 49.1% |
| `gui/tabs/shared_order_logic.py` | 100.0% | 100.0% |
| `gui/tabs/shared_orders_window.py` | 56.3% | 50.7% |
| `pipelines/ordine_med.py` | 80.5% | 67.5% |
| `utility/backup.py` | 95.9% | 95.0% |
| `utility/notifications.py` | 91.0% | 77.9% |
| `utility/situazione_db.py` | 91.2% | 85.2% |
| `utility/source_manager.py` | 90.4% | 77.3% |
| `utility/ui_thread.py` | 100.0% | 100.0% |
| `utility/updater.py` | 70.3% | 51.9% |

### SQLite and data integrity (executed, real files and real processes)
| Scenario | Result |
|---|---|
| New database | created with every table and column |
| Databases exactly as 8 older releases left them (rebuilt from each release's own `init_db`) | all upgraded, every old row identical, second start changes nothing |
| Orders-history and Listini-cache databases of the older release | rows kept, new writes work |
| Program killed (SIGKILL) while saving, 4 timings | database opens, `integrity_check` ok, one complete snapshot (never a mix) |
| 3 writer processes + 1 reader at the same time | no "database is locked", no lost write, last snapshot of each writer complete |
| Backup taken while the data is only in the `-wal` file | backup contains it; restore brings back exactly that state |
| Stale `-wal` of the replaced database | not replayed onto the restored one |
| Backup holding a damaged database / file that is not a backup | refused, nothing replaced |
| Restart persistence (separate processes) | data identical, no duplicates, no lock left behind |

### Shared orders scenarios (executed, workbooks with the production headers)
Orders / PG-X split and numeric sort; re-append idempotent; assign Partita GG (right and wrong raw article, with and without confirmation); edit, move, delete rows;
shipped delete archived in the history; the open history always equals the workbook; Excel round trip (leading zeros, numbers); workbook of an older version migrated
(no Print column, waiting rows on Orders); locked workbook gives a clear message and stays intact; 1,500 rows; Partita GG upload (available / mismatching / missing batch
confirmed or declined / wrong headers / equal numbers in other formats / second upload refused); Auto-Assign.

## 6. Windows (evidence from the project's GitHub Actions, commit `8cb47a1`, read from branch `ci-reports`)

| Run | Result |
|---|---|
| `tests` Python 3.12 / 3.14 on Windows | **869 passed, 0 failed, 6 skipped** each (5 publish-script tests run on Ubuntu by design, 1 `win32com` environment test) |
| `windows-exe` | **success**: PyInstaller build, package contents check, packaged `Planning.exe` started on an empty profile and restarted on the saved one, closed |

These runs do **not** include the changes of section 3 (they were not pushed). **NOT VERIFIED on Windows:** all of section 3. Run `tools\verify_windows.ps1` (section 10).

## 7. Packaging (executed on Linux with the project's `main.spec`)
Build succeeded; 113 of 114 project modules are inside the archive (the remaining one is `runtime_hook`, executed at boot by design); `icon.ico`, `version.txt`
and `data/prezzi_category_map.json` are present; no database file is packaged; the **packaged binary** started on an empty profile, restarted on it and closed.
This confirms hidden imports and data files for the Linux build only; the Windows build is covered by the CI evidence in section 6.

## 8. CI report publishing (executed)
`ci/make_report.py` and `ci/publish_report.sh` were exercised on Ubuntu with relative and absolute paths, first publish (orphan branch), a second workflow on the same branch,
no-change, two publishers at the same moment, history pruning, a run without artifacts, and a missing folder. The relative-path defect that stopped the first deployment was
reproduced, fixed and has a regression test. Live: branch `ci-reports` exists with `latest/` and `history/`; every report names the commit and the run URL; `history/` keeps
earlier reports; `latest/` is overwritten by design. The workflow cannot loop (a push made with `GITHUB_TOKEN` starts no workflow), runs only for this repository's own runs,
takes its scripts from the default branch and has the two permissions it needs (`contents: write`, `actions: read`).

## 9. Version and project hygiene
`version.txt`, `installer.iss` (`AppVersion`) and `DEFAULT_APP_VERSION` in `utility/updater.py` all say **1.2.9**.
No secrets in the current files or in any of the 115 commits (token/key patterns scanned); no database, Excel, log or ZIP file is tracked; `.gitignore` covers logs, backups, databases and caches.
Stale reports were replaced or marked historical (`PERFORMANCE_REPORT.md`, `docs/history/`). Dependencies in `requirements.txt` are ranges, not pins (section 11).

## 10. Not executed / not verified — and how to verify
| What | Why | How |
|---|---|---|
| All code of section 3 on Windows (tests, build, EXE) | no Windows in the review environment | `powershell -ExecutionPolicy Bypass -File tools\verify_windows.ps1` (runs deps, full pytest, PyInstaller build, package check, EXE smoke; logs in `verify_logs\<time>`) |
| The update helper under Windows PowerShell 5.1 and in `C:\Program Files` with UAC and antivirus | needs Windows; updater tests run on `powershell.exe` when the suite runs on Windows | install the 1.2.9 build first, then verify an update from that version and read `%TEMP%\Planning_Update.log` |
| Manual end-to-end use of every page with production Excel files | production data is not available | planner acceptance test |
| `Planning_Backup` after a real update | needs a real update | after the test update, `C:\Program Files\Planning_Backup` must exist and equal the previous version |

## 11. Remaining issues
**High**
* After a failed update the user is not told (the old version simply starts again; the reason is only in `%TEMP%\Planning_Update.log`). Suggest an in-app notice on the next start.
**Medium**
* Auto-Assign: if its result cannot be delivered the "Assigning Stock..." window stays open; after a failure part-way the earlier rows stay assigned and the table is not refreshed (documented by a test).
* `_sync_workbook_history` hides a failing history at debug level (it must not stop saving, but should be a warning).
* `restore_backup` replaces files one by one (not atomic) once the databases pass the check.
* 100 broad handlers log without a traceback; large modules still low in coverage and made of closures: `shared_orders_window.py` 56%, `shared_order_actions.py` 62%, `situazione_tab.py`, `overview_tab.py`.
* `requirements.txt` ranges (pandas, numpy, pyinstaller) make two builds not guaranteed identical; a lock/constraints file is advisable for releases.
**Low**
* A Partita Col whose text is `nan` gives a NaN sort key (behaviour of the original code, left unchanged).
* No `PRAGMA user_version` in the databases (upgrades rely on idempotent column checks).

## 12. Release readiness
The code is **ready for the Windows verification step**, not yet for release. Before releasing: (1) `tools\verify_windows.ps1` passes on a Windows machine, (2) one real update of an installed
copy succeeds and a deliberate failure (e.g. antivirus-locked file) leaves the old version working, (3) the planners confirm the shared-orders pages with real files. No known defect blocks
(1)–(3); the critical updater defect is fixed and proven at script level only.
