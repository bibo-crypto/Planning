<#
.SYNOPSIS
    Full verification of this project on THIS Windows machine, with the logs kept in one folder.

.DESCRIPTION
    Runs, in order, and records the exit code and the full log of each step:
      1. dependencies          pip install -r requirements-dev.txt
      2. tests                 the complete pytest suite (junit xml + log)
      3. build                 PyInstaller, exactly like build.bat (main.spec)
      4. package               the packaged files are all there (Planning.exe, _internal\python3*.dll, version.txt, icon, data)
      5. exe smoke             the built Planning.exe starts on an EMPTY data folder, leaves the loading screen,
                               restarts on the data it left behind, and closes (ci\smoke_exe.py)
    Nothing is committed, pushed or uploaded; the application's real data folder is never touched (the smoke test points
    the program at a throw-away profile).

    Run from the project folder, in PowerShell:
        powershell -ExecutionPolicy Bypass -File tools\verify_windows.ps1
    Then send the folder verify_logs\<time>\ (or its .zip) to whoever reviews the result.
#>
$ErrorActionPreference = 'Continue'
$project = Split-Path -Parent $PSScriptRoot
Set-Location $project
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$out = Join-Path $project "verify_logs\$stamp"
New-Item -ItemType Directory -Path $out -Force | Out-Null

$python = Join-Path $project 'venv\Scripts\python.exe'
if (-not (Test-Path $python)) { $python = 'python' }
$results = @()

function Invoke-Step([string]$name, [scriptblock]$body) {
    Write-Host ""
    Write-Host "=== $name" -ForegroundColor Cyan
    $log = Join-Path $out ("{0}.log" -f ($name -replace '[^A-Za-z0-9]+', '_'))
    $started = Get-Date
    & $body *>&1 | Tee-Object -FilePath $log | Out-Host
    $code = $LASTEXITCODE
    $seconds = [int]((Get-Date) - $started).TotalSeconds
    $status = if ($code -eq 0) { 'PASS' } else { 'FAIL' }
    Write-Host ("--- {0}: {1} (exit {2}, {3}s)" -f $name, $status, $code, $seconds) -ForegroundColor $(if ($code -eq 0) { 'Green' } else { 'Red' })
    $script:results += [pscustomobject]@{ Step = $name; Result = $status; ExitCode = $code; Seconds = $seconds; Log = (Split-Path $log -Leaf) }
}

"Python : $(& $python --version 2>&1)" | Tee-Object -FilePath (Join-Path $out 'environment.txt')
"Windows: $([System.Environment]::OSVersion.VersionString)" | Tee-Object -FilePath (Join-Path $out 'environment.txt') -Append
"Version: $(Get-Content (Join-Path $project 'version.txt') -Raw)" | Tee-Object -FilePath (Join-Path $out 'environment.txt') -Append

Invoke-Step 'dependencies' { & $python -m pip install -r requirements-dev.txt }
# pytest's scratch folder (--basetemp).  The default one (%TEMP%\pytest-of-<user>) is not writable by pytest on some user
# profiles, so a fresh folder is used.  It goes under %TEMP% -- OUTSIDE the project: the project is a Git repository, and a
# scratch folder inside it made "is this folder a Git repository?" tests find the project's own .git (tests/conftest.py now
# also stops git at the scratch folder, so even the fallback below is safe).
$baseTemp = Join-Path $env:TEMP "planning_verify_$stamp"
try {
    New-Item -ItemType Directory -Path $baseTemp -Force -ErrorAction Stop | Out-Null
    $probe = Join-Path $baseTemp 'write_probe.tmp'
    Set-Content -Path $probe -Value 'ok' -ErrorAction Stop
    Remove-Item -Path $probe -Force -ErrorAction Stop
} catch {
    Write-Host "WARNING: cannot write to $baseTemp ($($_.Exception.Message)); using $out\pytest_tmp instead" -ForegroundColor Yellow
    $baseTemp = Join-Path $out 'pytest_tmp'
}
"pytest basetemp: $baseTemp" | Tee-Object -FilePath (Join-Path $out 'environment.txt') -Append

Invoke-Step 'tests' {
    # pytest deletes and re-creates the --basetemp folder itself, so it must be a folder that is used for nothing else.
    & $python -m pytest -q -rfEs --tb=short --basetemp $baseTemp --junitxml (Join-Path $out 'junit.xml')
}
Invoke-Step 'build' { & $python -m PyInstaller main.spec --noconfirm }
Invoke-Step 'package' {
    $root = Join-Path $project 'dist\Planning'
    $problems = @()
    if (-not (Test-Path (Join-Path $root 'Planning.exe'))) { $problems += 'Planning.exe is missing' }
    if (-not (Get-ChildItem (Join-Path $root '_internal') -Filter 'python3*.dll' -ErrorAction SilentlyContinue)) { $problems += '_internal\python3*.dll is missing' }
    foreach ($name in @('icon.ico', 'version.txt', 'prezzi_category_map.json')) {
        if (-not (Get-ChildItem $root -Recurse -File -Filter $name -ErrorAction SilentlyContinue)) { $problems += "$name is not in the package" }
    }
    if (Get-ChildItem $root -Recurse -File -Include *.db, *.sqlite, *.sqlite3 -ErrorAction SilentlyContinue) { $problems += 'a database file is in the package' }
    Get-ChildItem $root | Format-Table Name, Length
    if ($problems) { $problems | ForEach-Object { Write-Host "PROBLEM: $_" }; $global:LASTEXITCODE = 1 } else { Write-Host 'package contents OK'; $global:LASTEXITCODE = 0 }
}
Invoke-Step 'exe smoke' {
    & $python ci\smoke_exe.py --exe (Join-Path $project 'dist\Planning\Planning.exe') --data-root (Join-Path $out 'smoke_profile') --timeout 150
}

Write-Host ""
Write-Host "================ SUMMARY ================" -ForegroundColor Yellow
$results | Format-Table -AutoSize | Out-String | Tee-Object -FilePath (Join-Path $out 'SUMMARY.txt') | Write-Host
Copy-Item -Path (Join-Path $project 'dist\Planning\*.log') -Destination $out -ErrorAction SilentlyContinue
Compress-Archive -Path "$out\*" -DestinationPath "$out.zip" -Force
Write-Host "Logs: $out"
Write-Host "Zip : $out.zip"
if ($results | Where-Object { $_.Result -ne 'PASS' }) { exit 1 } else { exit 0 }
