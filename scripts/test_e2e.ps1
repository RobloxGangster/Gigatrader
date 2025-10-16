#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$LOGROOT = Join-Path $ROOT 'logs'
$TLOG    = Join-Path $LOGROOT 'tests'
New-Item -ItemType Directory -Force -Path $TLOG | Out-Null

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOGFILE = Join-Path $TLOG "test_e2e-$stamp.log"

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

# --- dev deps + browsers ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt" | Tee-Object $LOGFILE -Append | Write-Host
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 2>&1 | Tee-Object $LOGFILE -Append | Write-Host
}
Log "[STEP] playwright install chromium" | Tee-Object $LOGFILE -Append | Write-Host
& $PYEXE -m playwright install chromium 2>&1 | Tee-Object $LOGFILE -Append | Write-Host

# --- env defaults ---
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = 'true' }   # safe default
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = '8000' }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = '8501' }
if (-not $env:PYTHONPATH)  { $env:PYTHONPATH  = $ROOT }

# --- show discovered e2e tests ---
Log "[INFO] E2E test files under /tests/e2e:" | Tee-Object $LOGFILE -Append | Write-Host
Get-ChildItem -Recurse -File -Path (Join-Path $ROOT 'tests\e2e') -Filter '*.py' -ErrorAction SilentlyContinue `
  | Select-Object FullName `
  | ForEach-Object { $_.FullName } `
  | Tee-Object $LOGFILE -Append | Write-Host

# --- run e2e (Playwright) with LIVE console output ---
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$plugins = @('-p','pytest_playwright')
& $PYEXE -m pip show pytest-asyncio 1>$null 2>$null
if ($LASTEXITCODE -eq 0) { $plugins += @('-p','pytest_asyncio') }

Log "[STEP] pytest -m e2e (plugins: $($plugins -join ' '))" | Tee-Object $LOGFILE -Append | Write-Host
& $PYEXE -m pytest -m e2e tests/e2e -rA --screenshot=off --video=off --tracing=off @plugins 2>&1 `
  | Tee-Object $LOGFILE -Append | Write-Host

$rc = $LASTEXITCODE
if ($rc -ne 0) {
  Log "[ERR] pytest e2e exited with $rc" | Tee-Object $LOGFILE -Append | Write-Host
  Pause-And-Exit $rc
}

Log "[OK] test_e2e passed" | Tee-Object $LOGFILE -Append | Write-Host
Pause-And-Exit 0
