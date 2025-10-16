#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- repo root ---
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$LOGDIR  = Join-Path $ROOT 'logs\tests'
New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null

# --- single timestamped log ---
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOGFILE = Join-Path $LOGDIR "test_all_in_one-$stamp.log"

function Log([string]$m) {
  $ts = Get-Date -Format 'u'
  "$ts $m"
}
function Pause-And-Exit([int]$rc) {
  Write-Host ""
  Write-Host "• Log: $LOGFILE"
  Write-Host "• Exit code: $rc"
  Read-Host "[Press Enter to close]"
  exit $rc
}

Log "=== unified test run start; ROOT=$ROOT ===" | Tee-Object $LOGFILE -Append | Write-Host

# --- venv / python ---
$VENV  = Join-Path $ROOT '.venv'
$PYEXE = Join-Path $VENV 'Scripts\python.exe'
if (-not (Test-Path $PYEXE)) {
  Log "[INFO] .venv missing; creating..." | Tee-Object $LOGFILE -Append | Write-Host
  & py -3.11 -m venv $VENV 2>&1 | Tee-Object $LOGFILE -Append | Write-Host
  if (-not (Test-Path $PYEXE)) {
    Log "[ERR] Failed to create venv" | Tee-Object $LOGFILE -Append | Write-Host
    Pause-And-Exit 1
  }
}
(& $PYEXE -V) 2>&1 | Tee-Object $LOGFILE -Append | Write-Host

# --- install dev deps ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt" | Tee-Object $LOGFILE -Append | Write-Host
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 2>&1 | Tee-Object $LOGFILE -Append | Write-Host
} else {
  Log "[WARN] requirements-dev.txt not found; continuing..." | Tee-Object $LOGFILE -Append | Write-Host
}

# --- env defaults (safe) ---
if (-not $env:PYTHONPATH) { $env:PYTHONPATH = $ROOT }
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = '8000' }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = '8501' }
# MOCK_MODE can be true or false; default to true for safe CI unless user set it
if (-not $env:MOCK_MODE)   { $env:MOCK_MODE   = 'true' }

# --- list tests that will run ---
Log "[INFO] Discovering tests under /tests" | Tee-Object $LOGFILE -Append | Write-Host
Get-ChildItem -Recurse -File -Path (Join-Path $ROOT 'tests') -Filter '*.py' -ErrorAction SilentlyContinue `
  | Select-Object FullName `
  | ForEach-Object { $_.FullName } `
  | Tee-Object $LOGFILE -Append | Write-Host

# --- PHASE 1: run ALL non-E2E tests in one go ---
Log "[STEP] PYTEST (non-E2E): tests -m \"not e2e\" -rA --ignore=tests\\e2e --maxfail=1" | Tee-Object $LOGFILE -Append | Write-Host
& $PYEXE -m pytest tests -rA -m "not e2e" --ignore=tests\e2e --maxfail=1 2>&1 `
  | Tee-Object $LOGFILE -Append | Write-Host
$rc1 = $LASTEXITCODE
if ($rc1 -ne 0) {
  Log "[WARN] non-E2E tests failed with exit code $rc1 (continuing to E2E to collect full picture)" `
    | Tee-Object $LOGFILE -Append | Write-Host
}

# --- PHASE 2: ensure Playwright browser; then run E2E tests ---
Log "[STEP] playwright install chromium" | Tee-Object $LOGFILE -Append | Write-Host
& $PYEXE -m playwright install chromium 2>&1 | Tee-Object $LOGFILE -Append | Write-Host

Log "[STEP] PYTEST (E2E): -m e2e -rA" | Tee-Object $LOGFILE -Append | Write-Host
& $PYEXE -m pytest -m e2e tests/e2e -rA 2>&1 `
  | Tee-Object $LOGFILE -Append | Write-Host
$rc2 = $LASTEXITCODE

# --- final combined exit status ---
$final = if ($rc1 -ne 0 -or $rc2 -ne 0) { 1 } else { 0 }
if ($final -ne 0) {
  Log "[ERR] unified test run FAILED (unit/integration rc=$rc1, e2e rc=$rc2)" | Tee-Object $LOGFILE -Append | Write-Host
} else {
  Log "[OK] unified test run PASSED (rc=0)" | Tee-Object $LOGFILE -Append | Write-Host
}
Pause-And-Exit $final
