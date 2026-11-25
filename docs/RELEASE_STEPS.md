# Publishing a release the in-app updater will accept

How updating works (pinned by `tests/test_update_system.py`): the program asks GitHub for the **latest release**, takes its **tag**
(`v1.3.8`) as the new version, downloads the first `.zip` asset (it prefers one named `Planning...zip`), unpacks it, refuses it if it
is not a whole program (`Planning.exe` and `_internal\python3*.dll`), and starts a short PowerShell helper that waits for the
program to close, backs up the installation, copies the new files, writes the **tag** into `version.txt`, starts the new program and
rolls back if it does not stay running. After an update the program reports the tag, whatever the number in the file name or in the ZIP.

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

* The program starts the helper and **waits up to 25 s** (3 minutes behind the Windows permission prompt) for its start marker before it
  closes. If the marker does not come, the program **stays open**, withdraws the update and says that Windows or an antivirus most likely
  blocked the helper. A helper that starts later finds the withdrawal and changes nothing.
* **Antivirus.** RAV Endpoint Protection removed the earlier, long helper (`Planning_UpdateBootstrap_*.ps1`, "Suspicious PowerShell
  script activity", Risk.Powershell.Script.Gen.DIYST). The helper is now the short script of the first working release and
  `tests/test_update_system.py` fails if it grows long or contains what antivirus products look for (`Add-Type`, message boxes, hashing,
  downloads, encoded commands, .NET calls). If an antivirus still blocks it, add an exception for `%TEMP%\Planning_Update_*.ps1`
  (or the whole `%TEMP%` script folder) and for the install folder.
* If the helper rolls back or fails, it writes `%LOCALAPPDATA%\Planning\update_failed.txt`; the program shows its content once at the next
  start. The helper's own log is `%TEMP%\Planning_Update.log`.
* A backup that is not complete is never used for a rollback: the installation is left exactly as it was.

## What to send when an update fails

1. The message the program showed (also in `converter.log`: look for `Update to ...`).
2. `%TEMP%\Planning_Update.log`, if it exists, and `%LOCALAPPDATA%\Planning\update_failed.txt`, if it exists.
3. The antivirus alert (name of the program and of the file it names).
