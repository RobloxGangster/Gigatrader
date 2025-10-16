#Requires -Version 5.1
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Log([string]$m) { "$([DateTime]::UtcNow.ToString('u')) $m" }
function Pause-And-Exit([int]$rc, [string]$log) {
  Write-Host "`n• Log: $log`n• Exit code: $rc"
  Read-Host "[Press Enter to close]"
  exit $rc
}

# --- repo root & log ---
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT   = (Get-Location).Path
$LOGDIR = Join-Path $ROOT 'logs\tests'
New-Item -ItemType Directory -Force -Path $LOGDIR | Out-Null
$stamp  = Get-Date -Format 'yyyyMMdd-HHmmss'
$LOG    = Join-Path $LOGDIR "test_all_in_one-$stamp.log"

Log "=== unified test start; ROOT=$ROOT ===" | Tee-Object $LOG -Append | Write-Host

# --- venv / python ---
$VENV  = Join-Path $ROOT '.venv'
$PYEXE = Join-Path $VENV 'Scripts\python.exe'
if (-not (Test-Path $PYEXE)) {
  Log "[INFO] .venv missing; creating..." | Tee-Object $LOG -Append | Write-Host
  & py -3.11 -m venv $VENV 2>&1 | Tee-Object $LOG -Append | Write-Host
  if (-not (Test-Path $PYEXE)) { Log "[ERR] Failed to create venv" | Tee-Object $LOG -Append | Write-Host; Pause-And-Exit 1 $LOG }
}
(& $PYEXE -V) 2>&1 | Tee-Object $LOG -Append | Write-Host

# --- dev deps ---
if (Test-Path (Join-Path $ROOT 'requirements-dev.txt')) {
  Log "[STEP] pip install -r requirements-dev.txt" | Tee-Object $LOG -Append | Write-Host
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 2>&1 | Tee-Object $LOG -Append | Write-Host
}

# --- env defaults ---
if (-not $env:PYTHONPATH) { $env:PYTHONPATH = $ROOT }
if (-not $env:GT_API_PORT) { $env:GT_API_PORT = '8000' }
if (-not $env:GT_UI_PORT)  { $env:GT_UI_PORT  = '8501' }
if (-not $env:MOCK_MODE)   { $env:MOCK_MODE   = 'true' }

# --- helper to conditionally add pytest plugins ---
function Add-PluginIfPresent([ref]$arr, [string]$pkg, [string]$pluginModule) {
  & $PYEXE -m pip show $pkg 1>$null 2>$null
  if ($LASTEXITCODE -eq 0) {
    $arr.Value += @('-p', $pluginModule)
  }
}

# --- ensure no stray Playwright artifacts ---
$PW_RESULTS = Join-Path $ROOT 'test-results'
if (Test-Path $PW_RESULTS) { Remove-Item -Recurse -Force $PW_RESULTS -ErrorAction SilentlyContinue }

# ===================== PHASE 1: NON-E2E =====================
Log "[STEP] PYTEST (non-E2E): tests -m 'not e2e' --ignore=tests\\e2e" | Tee-Object $LOG -Append | Write-Host

# Disable autoload to avoid 3rd-party option conflicts (e.g., --screenshot)
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$plugins1 = @()
# SAFE WHITELIST for unit/integration: add if installed
Add-PluginIfPresent ([ref]$plugins1) 'pytest-env'     'pytest_env'
Add-PluginIfPresent ([ref]$plugins1) 'pytest-dotenv'  'pytest_dotenv'
Add-PluginIfPresent ([ref]$plugins1) 'pytest-asyncio' 'pytest_asyncio'
# (do NOT load playwright/selenium/etc here)

& $PYEXE -m pytest tests -rA -m "not e2e" --ignore=tests\e2e @plugins1 2>&1 `
  | Tee-Object $LOG -Append | Write-Host
$rc1 = $LASTEXITCODE
if ($rc1 -ne 0) {
  Log "[WARN] non-E2E failed with rc=$rc1 (continuing to E2E)" | Tee-Object $LOG -Append | Write-Host
}

# ===================== PHASE 2: E2E (PLAYWRIGHT) =====================
Log "[STEP] playwright install chromium" | Tee-Object $LOG -Append | Write-Host
& $PYEXE -m playwright install chromium 2>&1 | Tee-Object $LOG -Append | Write-Host

# E2E: keep autoload disabled; explicitly load Playwright (and asyncio if present)
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
$plugins2 = @()
# Try both module names to guarantee the 'page' fixture:
Add-PluginIfPresent ([ref]$plugins2) 'pytest-playwright' 'pytest_playwright'
Add-PluginIfPresent ([ref]$plugins2) 'pytest-playwright' 'pytest_playwright.pytest_plugin'
Add-PluginIfPresent ([ref]$plugins2) 'pytest-asyncio'    'pytest_asyncio'

Log "[STEP] PYTEST (E2E): -m e2e -rA (plugins: $($plugins2 -join ' '))" | Tee-Object $LOG -Append | Write-Host
& $PYEXE -m pytest -m e2e tests/e2e -rA --screenshot=off --video=off --tracing=off @plugins2 2>&1 `
  | Tee-Object $LOG -Append | Write-Host
$rc2 = $LASTEXITCODE

# belt & suspenders: remove any test-results
if (Test-Path $PW_RESULTS) { Remove-Item -Recurse -Force $PW_RESULTS -ErrorAction SilentlyContinue }

# --- final summary ---
$final = if ($rc1 -ne 0 -or $rc2 -ne 0) { 1 } else { 0 }
if ($final -ne 0) {
  Log "[ERR] unified test run FAILED (unit/integration rc=$rc1, e2e rc=$rc2)" | Tee-Object $LOG -Append | Write-Host
} else {
  Log "[OK] unified test run PASSED (rc=0)" | Tee-Object $LOG -Append | Write-Host
}
Pause-And-Exit $final $LOG
