# Not executed / not verified
- A real update on Windows (Windows PowerShell 5.1, antivirus, UAC, Program Files). The failure the owner saw after his tag change was NOT reproduced; its cause is unknown (no message was supplied).
- The update logic WAS run on Linux with PowerShell 7 against the real published v1.3.7 asset (3364 files): staging, helper, installed version.txt = tag.
- The 8.3 short-path test and the non-root permission test are skipped on Linux.
- PyInstaller build, EXE smoke test.
