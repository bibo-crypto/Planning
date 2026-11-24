# Publishing a release the in-app updater can install

The in-app updater uses the standard Inno Setup executable, not a temporary PowerShell script. It downloads
`Planning_Setup_v<version>.exe` from the latest GitHub release and opens the Setup wizard. If Planning is installed under
`Program Files`, approve the normal Windows Administrator prompt. Setup closes Planning when it needs to replace its files.

## Build and publish (Windows)

1. Set the same new version in `version.txt`, `installer.iss` (`AppVersion`), `utility/updater.py` (`DEFAULT_APP_VERSION`),
   and `EXPECTED` in `tests/test_version_consistency.py`.
2. Run `build.bat`. It builds the app, creates and checks the version-independent `dist\Planning.zip`, and compiles
   `installer_output\Planning_Setup_v<version>.exe` with Inno Setup 6.
3. Create a GitHub release tagged `v<version>` and upload both `Planning_Setup_v<version>.exe` and **`Planning.zip`**. The
   ZIP name is fixed; the release tag is the version. The current updater uses the Setup EXE.
4. Verify both assets are present and that the release tag matches the build version.

## Migrating older installations

Installations using the old ZIP/PowerShell updater cannot update themselves to the Setup-based updater. Download the Setup EXE
from the latest release and run it once manually. Future in-app updates will use Setup.

## If Setup does not start

* Approve the Windows Administrator prompt when the installation is under `Program Files`.
* If Windows or endpoint protection blocks the Setup EXE, use the official release asset and follow your organization's
  software-approval process. Do not disable antivirus protection.
* If Setup opens but the update fails, note the message shown by Setup and the version/tag being installed.
