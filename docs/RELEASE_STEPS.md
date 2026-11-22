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
