# Publishing a release the in-app updater will accept

The updater downloads `Planning.zip` from the latest GitHub release, unpacks it, and refuses it unless:

1. it holds `Planning.exe` and `_internal\python3*.dll` (the whole program folder, not only the exe);
2. the release tag is newer than the installed version. The tag is written as the installed version after the files are copied;
   the ZIP name and any bundled `version.txt` do not determine it.

## Steps (from the project folder, on the Windows build machine)

1. Run `build.bat`. It builds the program and always creates **`dist\Planning.zip`**.
2. `python tools\check_release_zip.py dist\Planning.zip` - must print `OK`.
3. Create the GitHub release with the tag `v<version>` and upload **`dist\Planning.zip`**. The tag, not the ZIP name,
   becomes the installed version.
   Do **not** zip `Planning.exe` yourself: the v1.3.2 and v1.3.5 releases held only the exe (14 MB) and every update from them
   stops with "the update package is incomplete".
4. After uploading, check what GitHub really serves:
   `python tools\check_release_zip.py https://github.com/<owner>/Planning/releases/download/v<version>/Planning.zip`.
5. A tag/asset that is already wrong cannot be repaired by the program: delete that release's asset and upload the right one,
   or publish the next version number.

## How the version works (pinned by `tests/test_update_version_authority.py`)

* The tag of the latest release is the version the program has after an update. The ZIP name and the `version.txt` inside the ZIP
  may say anything (or be missing); the updater writes the tag into the staged `version.txt` (and into `_internal\version.txt`
  when present) before touching the installation, and the helper writes it once more after the copy was verified.
* The program reads the external `version.txt` first (`_internal\version.txt` only as a fallback), so after an update it
  reports the tag and the next check offers only a release newer than that.
* A failed update restores the old files together with the old `version.txt`.

## When an update fails - what to send

1. The message the program showed (it is also in `converter.log`: look for `Update to ...`).
2. `%TEMP%\Planning_Update.log` - it now records the phases with timings: "Update helper started", "Backup ... verified (N files, S s)",
   "New version copied and verified", "version.txt now says ...", "The new version is running". The last line present is where it stopped.
3. `%LOCALAPPDATA%\Planning\update_failed.txt`, if it exists (the reason of a rollback).

