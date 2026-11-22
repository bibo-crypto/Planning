# Not executed / not verified
- Windows: real update (8.3 path, SHA-256 manifests, rollback message), verify_windows.ps1 as a whole, PyInstaller build, EXE smoke, Windows PowerShell 5.1.
- The 8.3 short-path test and the non-root permission test are skipped on Linux.
- Speed on the user's real data (Situazione, PDFs) and in the packaged EXE.
- Result window of 10 s: a result that cannot be shown within 10 s (modal dialog open longer) is dropped (flag released) - by design.
