#Requires -Version 5.1
param(
  [int]$ApiPort = 8000,
  [int]$UiPort = 8501,
  [switch]$VerboseMode
)

$ErrorActionPreference = 'Stop'
$PSDefaultParameterValues['Out-File:Encoding'] = 'utf8'

# --- Paths & logs ---
Set-Location -LiteralPath (Join-Path $PSScriptRoot '..')
$ROOT    = (Get-Location).Path
$RUNTIME = Join-Path $ROOT 'runtime'
$LOGDIR  = Join-Path $ROOT 'logs'
$VENV    = Join-Path $ROOT '.venv'
$PYEXE   = Join-Path $VENV 'Scripts\python.exe'
New-Item -ItemType Directory -Force -Path $RUNTIME | Out-Null
New-Item -ItemType Directory -Force -Path $LOGDIR  | Out-Null

# rotate logs/setup.log if present
$LOGFILE = Join-Path $LOGDIR 'setup.log'
if (Test-Path $LOGFILE) {
  $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss')
  Move-Item -Force -LiteralPath $LOGFILE -Destination (Join-Path $LOGDIR "setup-$stamp.log")
}
"===== Gigatrader setup started $(Get-Date -Format 'u') =====`nROOT=$ROOT" | Out-File $LOGFILE

function Log([string]$msg) {
  $stamp = (Get-Date -Format 'u')
  "$stamp $msg" | Tee-Object -FilePath $LOGFILE -Append | Out-Host
}
function AppendFile([string]$path) {
  if (Test-Path $path) {
    "---------- $(Split-Path $path -Leaf) ----------" | Out-File $LOGFILE -Append
    Get-Content -Raw -LiteralPath $path | Out-File $LOGFILE -Append
    "`n" | Out-File $LOGFILE -Append
  } else {
    "(missing) $path" | Out-File $LOGFILE -Append
  }
}
function Pause-And-Exit([int]$rc) {
  Write-Host ""
  Read-Host "[Press Enter to close]"
  exit $rc
}
function Fail([string]$step, [int]$rc=1) {
  Log "[ERR] Failure step=$step rc=$rc"
  # Env snapshot
  $envDump = Join-Path $RUNTIME "_env.txt"
  @"
=== ENV SNAPSHOT ===
DATE/TIME: $(Get-Date -Format 'u')
OS: $($env:OS)
ROOT: $ROOT
VENV: $VENV
USERPROFILE: $($env:USERPROFILE)
PROCESSOR_ARCHITECTURE: $($env:PROCESSOR_ARCHITECTURE)
PATH (first 5): $(($env:PATH -split ';')[0..([Math]::Min(4,($env:PATH -split ';').Count-1))] -join "`n  ")
"@ | Out-File $envDump
  AppendFile $envDump
  AppendFile (Join-Path $RUNTIME '_pyver.txt')
  AppendFile (Join-Path $RUNTIME '_venv_create.txt')
  AppendFile (Join-Path $RUNTIME '_clean.txt')
  AppendFile (Join-Path $RUNTIME '_pip_upgrade.out')
  AppendFile (Join-Path $RUNTIME '_pip_upgrade.err')
  AppendFile (Join-Path $RUNTIME '_pip_core.out')
  AppendFile (Join-Path $RUNTIME '_pip_core.err')
  AppendFile (Join-Path $RUNTIME '_pip_dev.out')
  AppendFile (Join-Path $RUNTIME '_pip_dev.err')
  AppendFile (Join-Path $RUNTIME '_pipver.txt')
  AppendFile (Join-Path $RUNTIME '_piplist.txt')
  AppendFile (Join-Path $RUNTIME '_pytest.txt')
  AppendFile (Join-Path $RUNTIME 'backend.out.log')
  AppendFile (Join-Path $RUNTIME 'backend.err.log')
  AppendFile (Join-Path $RUNTIME '_health.txt')
  AppendFile (Join-Path $RUNTIME 'streamlit.out.log')
  AppendFile (Join-Path $RUNTIME 'streamlit.err.log')
  "===== END OF FAILURE REPORT =====" | Out-File $LOGFILE -Append
  Pause-And-Exit $rc
}

function Test-PortFree([int]$port) {
  try {
    $used = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $port }
    return -not $used
  } catch {
    # Fallback on older Windows: assume free (we’ll detect via health later)
    return $true
  }
}

# --- New: Clean up old failed launches & residue ---
function Cleanup-OldLaunchResidue() {
  Log "[CLEANUP] Checking for previous failed launches…"

  # Kill prior backend by PID if recorded
  $pidFile = Join-Path $RUNTIME 'backend.pid'
  if (Test-Path $pidFile) {
    $pid = Get-Content -LiteralPath $pidFile -ErrorAction SilentlyContinue
    if ($pid) {
      try { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue; Log "[CLEANUP] Stopped previous backend PID $pid" } catch {}
    }
    Remove-Item -Force -LiteralPath $pidFile -ErrorAction SilentlyContinue
  }

  # If API port is occupied, try to free it
  if (-not (Test-PortFree $ApiPort)) {
    try {
      $owning = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $ApiPort } | Select-Object -First 1
      if ($owning) {
        Stop-Process -Id $owning.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        Log "[CLEANUP] Killed process on port $ApiPort (PID=$($owning.OwningProcess))"
      }
    } catch {}
  }

  # Kill any stray streamlit
  try {
    Get-Process -Name "streamlit" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue
    Log "[CLEANUP] Stopped stray Streamlit processes (if any)."
  } catch {}

  # Remove temp artifacts from prior scripts/runs
  foreach ($p in @(
    (Join-Path $RUNTIME '_reg_toy.py'),
    (Join-Path $RUNTIME '*.tmp')
  )) {
    Get-ChildItem -Path $p -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  }

  # Prune old logs (>14 days) in logs/ and runtime/
  $cut = (Get-Date).AddDays(-14)
  foreach ($dir in @($LOGDIR, $RUNTIME)) {
    Get-ChildItem -Path $dir -File -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt $cut } | Remove-Item -Force -ErrorAction SilentlyContinue
  }
}

function Ensure-Python() {
  Log "[STEP] ensure_python"
  $py = (Get-Command py -ErrorAction SilentlyContinue)
  $python = (Get-Command python -ErrorAction SilentlyContinue)
  if (-not (Test-Path $PYEXE)) {
    Log "[INFO] Creating venv .venv (prefer py -3.11)…"
    try {
      if ($py) { & py -3.11 -m venv $VENV 2>&1 | Tee-Object (Join-Path $RUNTIME '_venv_create.txt') }
      elseif ($python) { & python -m venv $VENV 2>&1 | Tee-Object (Join-Path $RUNTIME '_venv_create.txt') }
      else { throw "No 'py' or 'python' found on PATH." }
    } catch {
      $_ | Out-File (Join-Path $RUNTIME '_venv_create.txt') -Append
      Fail 'create_venv'
    }
  }
  if (-not (Test-Path $PYEXE)) { Fail 'create_venv_not_found' }
  & $PYEXE -V 2>&1 | Tee-Object (Join-Path $RUNTIME '_pyver.txt') | Out-Null
  AppendFile (Join-Path $RUNTIME '_pyver.txt')
  Log "[OK] Using $PYEXE"
}

function Clean-Strays() {
  Log "[STEP] clean_site_packages"
  $site = & $PYEXE - << 'PY'
import site, sys
c=[p for p in site.getsitepackages() if p.endswith('site-packages')]
print(c[0] if c else sys.prefix)
PY
  if (Test-Path $site) {
    Get-ChildItem -LiteralPath $site -Filter '~*' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
  }
  # record action
  "site-packages at: $site" | Out-File (Join-Path $RUNTIME '_clean.txt')
}

function Pip-Install() {
  Log "[STEP] pip_install"
  Log "[INFO] Upgrading pip/setuptools/wheel…"
  & $PYEXE -m pip install --upgrade pip setuptools wheel 1> (Join-Path $RUNTIME '_pip_upgrade.out') 2> (Join-Path $RUNTIME '_pip_upgrade.err')
  if ($LASTEXITCODE -ne 0) { Fail 'upgrade_pip' $LASTEXITCODE }

  Log "[INFO] Installing requirements-core.txt…"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-core.txt') 1> (Join-Path $RUNTIME '_pip_core.out') 2> (Join-Path $RUNTIME '_pip_core.err')
  if ($LASTEXITCODE -ne 0) { Fail 'install_core_reqs' $LASTEXITCODE }

  Log "[INFO] Installing requirements-dev.txt…"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 1> (Join-Path $RUNTIME '_pip_dev.out') 2> (Join-Path $RUNTIME '_pip_dev.err')
  if ($LASTEXITCODE -ne 0) { Fail 'install_dev_reqs' $LASTEXITCODE }

  & $PYEXE -m pip --version > (Join-Path $RUNTIME '_pipver.txt') 2>&1
  & $PYEXE -m pip list --format=columns > (Join-Path $RUNTIME '_piplist.txt') 2>&1
}

function Self-TestModules() {
  Log "[STEP] module_self_test"
  $code = @"
import importlib
mods = ['fastapi','uvicorn','requests','streamlit']
missing = [m for m in mods if importlib.util.find_spec(m) is None]
print('MISSING=' + ','.join(missing))
"@
  $out = & $PYEXE - <<PY
$code
PY
  if ($out -match 'MISSING=') {
    $miss = $out.Trim() -replace '^MISSING=',''
    if ($miss) { Log "[ERR] Missing modules: $miss"; Fail 'module_check' 1 }
  }
}

function Launch-Backend() {
  Log "[STEP] launch_backend"
  if (-not (Test-PortFree $ApiPort)) {
    Log "[WARN] Port $ApiPort is in use; attempting cleanup…"
    Cleanup-OldLaunchResidue
  }
  if (-not (Test-PortFree $ApiPort)) { Fail 'port_in_use' 1 }

  Log "[INFO] Starting backend on :$ApiPort (uvicorn)…"
  $backendOut = Join-Path $RUNTIME 'backend.out.log'
  $backendErr = Join-Path $RUNTIME 'backend.err.log'
  $args = "-m","uvicorn","backend.api:app","--host","127.0.0.1","--port","$ApiPort"
  $p = Start-Process -FilePath $PYEXE -ArgumentList $args -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
  Set-Content -Path (Join-Path $RUNTIME 'backend.pid') -Value $p.Id
  Start-Sleep -Seconds 4

  try {
    $status = (Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 5).StatusCode
  } catch { $status = 0 }
  "$status" | Out-File (Join-Path $RUNTIME '_health.txt')
  if ($status -ne 200) {
    Log "[WARN] Health check failed ($status). Trying fallback 'python -m backend.server'…"
    try { Stop-Process -Id $p.Id -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    $args2 = "-m","backend.server"
    $p2 = Start-Process -FilePath $PYEXE -ArgumentList $args2 -RedirectStandardOutput $backendOut -RedirectStandardError $backendErr -PassThru
    Set-Content -Path (Join-Path $RUNTIME 'backend.pid') -Value $p2.Id
    Start-Sleep -Seconds 4
    try {
      $status = (Invoke-WebRequest -Uri "http://127.0.0.1:$ApiPort/health" -UseBasicParsing -TimeoutSec 5).StatusCode
    } catch { $status = 0 }
    "$status" | Out-File (Join-Path $RUNTIME '_health.txt')
    if ($status -ne 200) { Fail 'backend_health' 1 }
  }
  Log "[OK] Backend healthy (200)."
}

function Launch-UI() {
  Log "[STEP] launch_ui"
  Log "[INFO] Launching Streamlit UI on :$UiPort …"
  $uiOut = Join-Path $RUNTIME 'streamlit.out.log'
  $uiErr = Join-Path $RUNTIME 'streamlit.err.log'
  $args = @("run","ui\Home.py","--server.port",$UiPort,"--server.headless","true")
  Start-Process -FilePath (Join-Path $VENV 'Scripts\streamlit.exe') -ArgumentList $args -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr | Out-Null
}

# --------- main flow ----------
try {
  Log "[CLEANUP] Pre-run residue cleanup"
  Cleanup-OldLaunchResidue

  Ensure-Python
  Clean-Strays
  Pip-Install
  Self-TestModules
  Launch-Backend
  Launch-UI

  Log "===== Gigatrader setup finished $(Get-Date -Format 'u') ====="
  exit 0
} catch {
  $_ | Out-File $LOGFILE -Append
  Fail 'unhandled' 1
}
