#Requires -Version 5.1
$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$LOGROOT = Join-Path $ROOT 'logs'
$TLOG    = Join-Path $LOGROOT 'tests'
New-Item -ItemType Directory -Force -Path $TLOG | Out-Null

$stamp   = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOGFILE = Join-Path $TLOG "test_e2e-$stamp.log"
$SESSLOG = Join-Path $TLOG "test_e2e-$stamp.session.log"
"=== test_e2e start $(Get-Date -Format u) ===`nROOT=$ROOT" | Out-File $LOGFILE

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

# --- deps (dev + browsers) ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 1>> $LOGFILE 2>&1
}
Log "[STEP] playwright install chromium"
& $PYEXE -m playwright install chromium 1>> $LOGFILE 2>&1

# --- env defaults ---
if (-not $env:MOCK_MODE) { $env:MOCK_MODE = 'true' }     # safe default
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = '8000' }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = '8501' }
if (-not $env:PYTHONPATH)  { $env:PYTHONPATH  = $ROOT }

# --- start transcript ---
try { Start-Transcript -Path $SESSLOG -Force | Out-Null } catch {}

# --- run tests (e2e mark only) ---
Log "[STEP] pytest -m e2e"
& $PYEXE -m pytest -q -m e2e tests/e2e 1>> $LOGFILE 2>&1
$rc = $LASTEXITCODE
try { Stop-Transcript | Out-Null } catch {}

if ($rc -ne 0) {
  Log "[ERR] pytest e2e exited with $rc"
  Pause-And-Exit $rc
}
Log "[OK] test_e2e passed"
Pause-And-Exit 0
