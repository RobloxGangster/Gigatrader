#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- repo root ---
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$LOGROOT = Join-Path $ROOT 'logs'
$TLOG    = Join-Path $LOGROOT 'tests'
New-Item -ItemType Directory -Force -Path $TLOG | Out-Null

# --- log file (timestamped) ---
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOGFILE = Join-Path $TLOG "test_all-$stamp.log"

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
  Log "[INFO] .venv missing; creating..." | Tee-Object $LOGFILE -Append
  & py -3.11 -m venv $VENV 2>&1 | Tee-Object $LOGFILE -Append
  if (-not (Test-Path $PYEXE)) {
    Log "[ERR] Failed to create venv" | Tee-Object $LOGFILE -Append
    Pause-And-Exit 1
  }
}

(& $PYEXE -V) 2>&1 | Tee-Object $LOGFILE -Append | Write-Host

# --- dev deps ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt" | Tee-Object $LOGFILE -Append | Write-Host
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 2>&1 | Tee-Object $LOGFILE -Append | Write-Host
}

# --- env defaults ---
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = 'true' }
if (-not $env:PYTHONPATH) { $env:PYTHONPATH = $ROOT }

# --- show discovered tests (quick sanity) ---
Log "[INFO] Test files under /tests:" | Tee-Object $LOGFILE -Append | Write-Host
Get-ChildItem -Recurse -File -Path (Join-Path $ROOT 'tests') -Filter '*.py' `
  | Select-Object FullName `
  | ForEach-Object { $_.FullName } `
  | Tee-Object $LOGFILE -Append | Write-Host

# --- run tests (unit + integration) with LIVE console output ---
Log "[STEP] pytest (unit + integration)" | Tee-Object $LOGFILE -Append | Write-Host
# Use -rA for a clear end summary; avoid -q so we see progress
& $PYEXE -m pytest tests/unit tests/integration -rA --maxfail=1 2>&1 `
  | Tee-Object $LOGFILE -Append | Write-Host

$rc = $LASTEXITCODE
if ($rc -ne 0) {
  Log "[ERR] pytest exited with $rc" | Tee-Object $LOGFILE -Append | Write-Host
  Pause-And-Exit $rc
}

Log "[OK] test_all passed" | Tee-Object $LOGFILE -Append | Write-Host
Pause-And-Exit 0
