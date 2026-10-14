@echo off
setlocal enabledelayedexpansion
cd /d "%~dp0"

echo.
echo  ================================================
echo    Planning  ^|  Build Script
echo  ================================================
echo.

:: -- Check Python --------------------------------------------------------
python --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Python is not installed.
    echo          Install Python 3.10 or newer from: https://python.org
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)
python -c "import sys; raise SystemExit(0 if sys.version_info >= (3,10) else 1)"
if errorlevel 1 (
    echo  [ERROR] Python 3.10 or newer is required.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)
for /f "tokens=*" %%v in ('python --version 2^>^&1') do echo  [OK] %%v detected
echo.

:: -- Create or reuse virtual environment -----------------------------------
if exist venv\Scripts\python.exe (
    echo  [1/6]  Reusing existing virtual environment ^(venv^)...
    echo         Skipping recreation -- packages will be added/removed to
    echo         match requirements.txt instead of rebuilding from scratch.
) else (
    echo  [1/6]  Creating virtual environment ^(venv^)...
    if exist venv (
        echo         Found an incomplete venv folder, removing it first...
        rmdir /s /q venv
    )
    python -m venv venv
    if errorlevel 1 (
        echo  [ERROR] Failed to create venv.
        if not defined PLANNING_NO_PAUSE pause
        exit /b 1
    )
)
echo         Done.
echo.

:: -- Activate venv ---------------------------------------------------------
echo  [2/6]  Activating virtual environment...
call venv\Scripts\activate.bat
if errorlevel 1 (
    echo  [ERROR] Could not activate venv.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)
echo         Done.
echo.

:: -- Install dependencies ---------------------------------------------------
echo  [3/6]  Syncing dependencies with requirements.txt...
python -m pip install --upgrade pip --quiet
if errorlevel 1 (
    echo  [ERROR] Could not upgrade pip.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)
echo         Removing packages no longer needed...
python sync_venv_packages.py
echo         Installing/updating packages from requirements.txt...
python -m pip install -r requirements.txt --quiet
if errorlevel 1 (
    echo  [ERROR] pip install requirements.txt failed.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)
echo         Done.
echo.

:: -- Clean old build / dist ---------------------------------------------------
echo  [4/6]  Cleaning old build and dist folders...
if exist build  rmdir /s /q build
if exist dist   rmdir /s /q dist
echo         Done.
echo.

:: -- Build with PyInstaller ---------------------------------------------------
echo  [5/6]  Building executable with PyInstaller...
echo.
python -m PyInstaller main.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo  [ERROR] PyInstaller build FAILED.
    echo          Check the output above for details.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)


:: -- Legacy launcher (self-update bridge) -------------------------------------
:: Versions installed before the rename (Planing.exe) update themselves by
:: looking for "Planing.exe" in the release ZIP and starting it afterwards.
:: A copy of the launcher under the old name lets them update to this build.
:: Safe to delete once every PC runs a Planning build.
copy /y "dist\Planning\Planning.exe" "dist\Planning\Planing.exe" >nul

:: -- Release hygiene ---------------------------------------------------------
:: Runtime state belongs in %%LOCALAPPDATA%%\Planning, never in a distributable
:: ZIP/setup.  The spec does not bundle these folders, but remove them here as
:: a final guard against a manually copied database or cache file.
echo  [6/6]  Removing runtime data from release and creating clean ZIP...
for %%D in (cache settings logs backups situazione) do (
    if exist "dist\Planning\%%D" rmdir /s /q "dist\Planning\%%D"
)
for /r "dist\Planning" %%F in (*.db *.sqlite *.sqlite3 *.pkl) do del /q "%%F"
for /r "dist\Planning" %%F in (*.db-* *.sqlite-* *.sqlite3-*) do del /q "%%F"
for /f "usebackq tokens=*" %%V in ("version.txt") do set "PLANNING_VERSION=%%V"
powershell -NoProfile -ExecutionPolicy Bypass -Command "Compress-Archive -Path 'dist\Planning\*' -DestinationPath 'dist\Planning_v!PLANNING_VERSION!.zip' -Force"
if errorlevel 1 (
    echo  [ERROR] Could not create the release ZIP.
    if not defined PLANNING_NO_PAUSE pause
    exit /b 1
)

echo.
echo  ================================================
echo    Build Complete!
echo    Output folder: dist\Planning\
echo    Release ZIP:   dist\Planning_v!PLANNING_VERSION!.zip
echo  ================================================
echo.
echo  Next step - create the installer:
echo    1. Install Inno Setup 6 from: https://jrsoftware.org/isdl.php
echo    2. Open installer.iss with Inno Setup Compiler
echo    3. Press Ctrl+F9 to compile
echo    4. The setup file will appear in: installer_output\
echo.
if not defined PLANNING_NO_PAUSE pause
