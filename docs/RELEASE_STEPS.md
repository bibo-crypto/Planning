# Publishing a release the in-app updater will accept

How updating works: the program asks GitHub for the **latest release**, takes its **tag** (`v1.3.8`) as the new version, downloads the
whole-folder ZIP, validates it before touching the installation, and starts the clearly named packaged `PlanningUpdater.exe`. The
updater waits for Planning to exit, makes and verifies a complete backup, copies the new files, writes the tag into `version.txt`,
launches Planning with a startup health marker, and restores the backup if startup fails. Runtime data remains in
`%LOCALAPPDATA%\Planning` and is never included in the release package.

## Steps (from the project folder, on the Windows build machine)

1. Set the new number in `version.txt`, `installer.iss` (`AppVersion`), `utility/updater.py` (`DEFAULT_APP_VERSION`) and
   `EXPECTED` in `tests/test_version_consistency.py` (a test keeps them equal).
2. `build.bat zip` - builds the program and creates **`dist\Planning_v<version>.zip`** from the whole `dist\Planning` folder, then
   checks it with `tools\check_release_zip.py` (it must print `OK`).
3. Create the GitHub release with the tag `v<version>` and upload **that ZIP**. Do **not** zip `Planning.exe` yourself: the v1.3.2 and
   v1.3.5 releases held only the exe (14 MB) and every update from them stopped with "the update package is incomplete".
4. After uploading, check what GitHub really serves:
   `python tools\check_release_zip.py https://github.com/<owner>/Planning/releases/download/v<version>/Planning_v<version>.zip --tag v<version>`.
5. A tag/asset that is already wrong cannot be repaired by the program: delete that release's asset and upload the right one, or publish
   the next version number.

## When something stops the update

* Planning waits up to 25 seconds for `PlanningUpdater.exe` to write its start marker before it closes. If the marker does not come,
  Planning stays open, nothing is changed, and the message identifies the updater path and log.
* The updater is a normal, separately packaged executable. It does not generate or execute PowerShell, add exclusions, disable security
  controls, hide its behavior, or download anything itself.
* A per-user install under `%LOCALAPPDATA%\Programs\Planning` normally needs no elevation. A legacy protected installation may show the
  standard Windows administrator prompt; declining it leaves the installed version intact.
* If the updater rolls back or fails, it writes `%LOCALAPPDATA%\Planning\update_failed.txt`; Planning shows its content once at the next
  start. The updater log is `%LOCALAPPDATA%\Planning\logs\updater.log`.
* A backup that is not complete is never used for a rollback: the installation is left exactly as it was.

## What to send when an update fails

1. The message the program showed (also in `converter.log`: look for `Update to ...`).
2. `%TEMP%\Planning_Update.log`, if it exists, and `%LOCALAPPDATA%\Planning\update_failed.txt`, if it exists.
3. The Windows Security or antivirus alert (product name and exact file/path named). Do not disable protection or add an automatic
   exclusion.

## Release assets

Upload `dist\Planning_v<version>.zip` produced by `build.bat zip` for the in-app updater. It must contain the contents of
`dist\Planning`, including `Planning.exe`, `PlanningUpdater.exe`, `_internal\python3*.dll`, and runtime files. The installer EXE is a
separate user-facing download and is not the in-app updater asset.

## Upgrade from the old Program Files installation

The current installer intentionally installs per-user at `%LOCALAPPDATA%\Programs\Planning`; it does not silently delete an older `C:\Program Files\Planning` installation. This avoids destroying user data or SQLite files before the new copy is verified. On a real Windows test machine:

1. Keep the old installation and its data intact, install the new setup, and confirm that the new Start Menu/Desktop shortcut points to `%LOCALAPPDATA%\Programs\Planning\Planning.exe`.
2. Start the new copy and verify the existing settings, workbooks, backups, and SQLite databases. The installer excludes runtime data from its payload and the updater copies only program files, so user data remains in `%LOCALAPPDATA%\Planning`.
3. Confirm there is no duplicate active shortcut. The installer removes the historical misspelled launcher shortcut and creates the correctly-spelled `Planning` shortcut.
4. Only after the new copy starts successfully and the data is verified, uninstall the old Program Files copy manually. Do not delete it as part of installation or before verification.

This migration requires a real Windows installation test; Linux tests and mocked tests do not prove UAC, shortcut, file-lock, or installer behavior.
