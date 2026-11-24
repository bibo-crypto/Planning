# Not executed / not verified
- A real update on Windows PowerShell 5.1 with the real antivirus (RAV Endpoint Protection). Whether RAV accepts the short script cannot be known from here.
- The Windows CI crash (0x80000003) is nondeterministic; the keep-alive guard in tests/conftest.py is not verified on Windows CI.
- PyInstaller build, `build.bat zip` itself (batch file; its text and CRLF endings are tested, it was not run), EXE smoke test.
