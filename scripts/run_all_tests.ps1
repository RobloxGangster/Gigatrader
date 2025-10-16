#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Log([string]$m) { "$([DateTime]::UtcNow.ToString('u')) $m" }
function Pause-And-Exit([int]$rc, [string]$log) {
  Write-Host "`n• Log: $log`n• Exit code: $rc"
  Read-Host "[Press Enter to close]"
  exit $rc
}

Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT   = (Get-Location).Path
$LOGDIR = Join-Path $ROOT 'logs\tests'
New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOG    = Join-Path $LOGDIR "test_all_in_one-$stamp.log"

Log "=== unified test start; ROOT=$ROOT ===" | Tee-Object $LOG -Append | Write-Host

$VENV  = Join-Path $ROOT '.venv'
$PYEXE = Join-Path $VENV 'Scripts\python.exe'
if (-not (Test-Path $PYEXE)) {
  Log "[INFO] .venv missing; creating..." | Tee-Object $LOG -Append | Write-Host
  & py -3.11 -m venv $VENV 2>&1 | Tee-Object $LOG -Append | Write-Host
  if (-not (Test-Path $PYEXE)) { Log "[ERR] Failed to create venv" | Tee-Object $LOG -Append | Write-Host; Pause-And-Exit 1 $LOG }
}
(& $PYEXE -V) 2>&1 | Tee-Object $LOG -Append | Write-Host

if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt" | Tee-Object $LOG -Append | Write-Host
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 2>&1 | Tee-Object $LOG -Append | Write-Host
}

if (-not $env:PYTHONPATH) { $env:PYTHONPATH = $ROOT }
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = '8000' }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = '8501' }
if (-not $env:MOCK_MODE)   { $env:MOCK_MODE   = 'true' }

$PW_RESULTS = Join-Path $ROOT 'test-results'
if (Test-Path $PW_RESULTS) { Remove-Item -Recurse -Force $PW_RESULTS -ErrorAction SilentlyContinue }

# ----------------- PHASE 1: non-E2E -----------------
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
# Always load asyncio plugin so async tests are supported
$plugins1 = @('-p','pytest_asyncio')

& $PYEXE -m pytest tests -rA -m "not e2e" --ignore=tests\e2e @plugins1 2>&1 `
  | Tee-Object $LOG -Append | Write-Host
$rc1 = $LASTEXITCODE
if ($rc1 -ne 0) {
  Log "[WARN] non-E2E failed with rc=$rc1 (continuing to E2E)" | Tee-Object $LOG -Append | Write-Host
}

# ----------------- PHASE 2: E2E (Playwright) -----------------
& $PYEXE -m pip show pytest-playwright 1>$null 2>$null
$hasPW = ($LASTEXITCODE -eq 0)

if ($hasPW) {
  Log "[STEP] playwright install chromium" | Tee-Object $LOG -Append | Write-Host
  & $PYEXE -m playwright install chromium 2>&1 | Tee-Object $LOG -Append | Write-Host

  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
  $plugins2 = @('-p','pytest_playwright','-p','pytest_asyncio')

  # Only pass PW flags when plugin is loaded
  $e2eArgs = @('-m','e2e','tests/e2e','-rA','--screenshot=off','--video=off','--tracing=off') + $plugins2
} else {
  Log "[STEP] pytest-playwright not installed; running E2E without PW flags" | Tee-Object $LOG -Append | Write-Host
  $env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
  $e2eArgs = @('-m','e2e','tests/e2e','-rA','-p','pytest_asyncio')
}

& $PYEXE -m pytest @e2eArgs 2>&1 | Tee-Object $LOG -Append | Write-Host
$rc2 = $LASTEXITCODE

if (Test-Path $PW_RESULTS) { Remove-Item -Recurse -Force $PW_RESULTS -ErrorAction SilentlyContinue }

$final = if ($rc1 -ne 0 -or $rc2 -ne 0) { 1 } else { 0 }
if ($final -ne 0) {
  Log "[ERR] unified test run FAILED (unit/integration rc=$rc1, e2e rc=$rc2)" | Tee-Object $LOG -Append | Write-Host
} else {
  Log "[OK] unified test run PASSED (rc=0)" | Tee-Object $LOG -Append | Write-Host
}
Pause-And-Exit $final $LOG
