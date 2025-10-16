#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# --- repo root ---
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$LOGROOT = Join-Path $ROOT 'logs'
$TLOG    = Join-Path $LOGROOT 'tests'
New-Item -ItemType Directory -Force -Path $TLOG | Out-Null

# --- logs (rotate) ---
$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOGFILE = Join-Path $TLOG "test_all-$stamp.log"
$SESSLOG = Join-Path $TLOG "test_all-$stamp.session.log"
"=== test_all start $(Get-Date -Format u) ===`nROOT=$ROOT" | Out-File $LOGFILE

function Log([string]$m) {
  $ts = Get-Date -Format 'u'
  "$ts $m" | Tee-Object -FilePath $LOGFILE -Append | Out-Host
}
function Pause-And-Exit([int]$rc) {
  Write-Host ""
  Write-Host "Log: $LOGFILE"
  Read-Host "[Press Enter to close]"
  exit $rc
}

# --- venv / python ---
$VENV  = Join-Path $ROOT '.venv'
$PYEXE = Join-Path $VENV 'Scripts\python.exe'
if (-not (Test-Path $PYEXE)) {
  Log "[INFO] .venv missing; creating..."
  & py -3.11 -m venv $VENV 2>&1 | Tee-Object -FilePath $LOGFILE -Append
  if (-not (Test-Path $PYEXE)) { Log "[ERR] Failed to create venv"; Pause-And-Exit 1 }
}
& $PYEXE -V 2>&1 | Tee-Object -FilePath $LOGFILE -Append | Out-Null

# --- deps (dev) ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 1>> $LOGFILE 2>&1
}

# --- env defaults ---
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = 'true' }
if (-not $env:PYTHONPATH) { $env:PYTHONPATH = $ROOT }

# --- start transcript (captures console too) ---
try { Start-Transcript -Path $SESSLOG -Force | Out-Null } catch {}

# --- run tests (unit + integration) ---
Log "[STEP] pytest unit + integration"
& $PYEXE -m pytest -q tests/unit tests/integration 1>> $LOGFILE 2>&1
$rc = $LASTEXITCODE
try { Stop-Transcript | Out-Null } catch {}

if ($rc -ne 0) {
  Log "[ERR] pytest exited with $rc"
  Pause-And-Exit $rc
}
Log "[OK] test_all passed"
Pause-And-Exit 0
