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

# rotate logs/setup.log
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
  } catch { return $true }
}

function Test-UIHealth([int]$timeoutSec = 30) {
  $deadline = (Get-Date).AddSeconds($timeoutSec)
  while ((Get-Date) -lt $deadline) {
    try {
      $resp = Invoke-WebRequest -Uri "http://127.0.0.1:$UiPort/" -UseBasicParsing -TimeoutSec 3
      if ($resp.StatusCode -in 200, 302, 303) { return $true }
    } catch { Start-Sleep -Milliseconds 500 }
  }
  return $false
}

function Open-UIBrowser() {
  try {
    Start-Process "http://127.0.0.1:$UiPort/"
  } catch {
    # non-fatal; user can open manually
  }
}

function Cleanup-OldLaunchResidue() {
  Log "[CLEANUP] Previous failed launches…"
  # Kill prior backend by PID if recorded (avoid collision with automatic $PID)
  $pidFile = Join-Path $RUNTIME 'backend.pid'
  if (Test-Path $pidFile) {
    try {
      $oldPid = Get-Content -LiteralPath $pidFile -ErrorAction Stop | Select-Object -First 1
    } catch {
      $oldPid = $null
    }
    if ($oldPid) {
      try {
        Stop-Process -Id [int]$oldPid -Force -ErrorAction SilentlyContinue
        Log "[CLEANUP] Stopped previous backend PID $oldPid"
      } catch {
        Log "[CLEANUP] Could not stop previous backend PID $oldPid (may not be running)."
      }
    }
    Remove-Item -Force -LiteralPath $pidFile -ErrorAction SilentlyContinue
  }
  if (-not (Test-PortFree $ApiPort)) {
    try {
      $owning = Get-NetTCPConnection -State Listen -ErrorAction SilentlyContinue | Where-Object { $_.LocalPort -eq $ApiPort } | Select-Object -First 1
      if ($owning) {
        Stop-Process -Id $owning.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 1
        if (-not (Test-PortFree $ApiPort)) {
          Log "[CLEANUP] Warning: port $ApiPort still appears busy after kill."
        } else {
          Log "[CLEANUP] Killed process on port $ApiPort (PID=$($owning.OwningProcess))"
        }
      }
    } catch {}
  }
  try { Get-Process -Name "streamlit" -ErrorAction SilentlyContinue | Stop-Process -Force -ErrorAction SilentlyContinue; Log "[CLEANUP] Stopped stray Streamlit" } catch {}
  foreach ($p in @((Join-Path $RUNTIME '_reg_toy.py'), (Join-Path $RUNTIME '*.tmp'))) {
    Get-ChildItem -Path $p -ErrorAction SilentlyContinue | Remove-Item -Force -ErrorAction SilentlyContinue
  }
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
      if     ($py)     { & py -3.11 -m venv $VENV 2>&1 | Tee-Object (Join-Path $RUNTIME '_venv_create.txt') }
      elseif ($python) { & python -m venv $VENV 2>&1 | Tee-Object (Join-Path $RUNTIME '_venv_create.txt') }
      else { throw "No 'py' or 'python' found on PATH." }
    } catch { $_ | Out-File (Join-Path $RUNTIME '_venv_create.txt') -Append; Fail 'create_venv' }
  }
  if (-not (Test-Path $PYEXE)) { Fail 'create_venv_not_found' }
  & $PYEXE -V 2>&1 | Tee-Object (Join-Path $RUNTIME '_pyver.txt') | Out-Null
  AppendFile (Join-Path $RUNTIME '_pyver.txt')
  Log "[OK] Using $PYEXE"
}

function Clean-Strays() {
  Log "[STEP] clean_site_packages"
  $pyCode = @'
import site, sys
c=[p for p in site.getsitepackages() if p.endswith("site-packages")]
print(c[0] if c else sys.prefix)
'@
  $site = & $PYEXE -c $pyCode 2>&1
  if ($LASTEXITCODE -ne 0 -or -not $site) { $site = $VENV }
  if (Test-Path $site) {
    Get-ChildItem -LiteralPath $site -Filter '~*' -Force -ErrorAction SilentlyContinue | Remove-Item -Recurse -Force -ErrorAction SilentlyContinue | Out-Null
  }
  "site-packages at: $site" | Out-File (Join-Path $RUNTIME '_clean.txt')
}

function Pip-Install() {
  Log "[STEP] pip_install"
  Log "[INFO] Upgrading pip/setuptools/wheel…"
  & $PYEXE -m pip install --upgrade pip setuptools wheel 1> (Join-Path $RUNTIME '_pip_upgrade.out') 2> (Join-Path $RUNTIME '_pip_upgrade.err'); if ($LASTEXITCODE -ne 0) { Fail 'upgrade_pip' $LASTEXITCODE }
  Log "[INFO] Installing requirements-core.txt…"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-core.txt') 1> (Join-Path $RUNTIME '_pip_core.out') 2> (Join-Path $RUNTIME '_pip_core.err'); if ($LASTEXITCODE -ne 0) { Fail 'install_core_reqs' $LASTEXITCODE }
  Log "[INFO] Installing requirements-dev.txt…"
  & $PYEXE -m pip install -r (Join-Path $ROOT 'requirements-dev.txt') 1> (Join-Path $RUNTIME '_pip_dev.out') 2> (Join-Path $RUNTIME '_pip_dev.err'); if ($LASTEXITCODE -ne 0) { Fail 'install_dev_reqs' $LASTEXITCODE }
  & $PYEXE -m pip --version > (Join-Path $RUNTIME '_pipver.txt') 2>&1
  & $PYEXE -m pip list --format=columns > (Join-Path $RUNTIME '_piplist.txt') 2>&1
}

function Self-TestModules() {
  Log "[STEP] module_self_test"
  $pyCode = @'
import importlib
mods = ["fastapi","uvicorn","requests","streamlit"]
missing = [m for m in mods if importlib.util.find_spec(m) is None]
print("MISSING=" + ",".join(missing))
'@
  $out = & $PYEXE -c $pyCode 2>&1
  if ($out -match '^MISSING=(.+)') {
    $miss = $Matches[1].Trim()
    if ($miss) { Log "[ERR] Missing modules: $miss"; Fail 'module_check' 1 }
  }
}

function Kill-PortBinding([int]$port) {
  try {
    $cmd = "netstat -ano | findstr :$port"
    $lines = & cmd /c $cmd 2>$null
  } catch {
    $lines = @()
  }
  $entries = @($lines)
  if (-not $entries -or $entries.Count -eq 0) { return }
  $pids = @()
  foreach ($entry in $entries) {
    $line = $entry.ToString().Trim()
    if (-not $line) { continue }
    $tokens = $line -split '\s+'
    if ($tokens.Length -ge 5) {
      $local = $tokens[1]
      if (-not $local.EndsWith(":$port")) { continue }
      $pidToken = $tokens[-1]
      if ($pidToken -match '^[0-9]+$') { $pids += [int]$pidToken }
    }
  }
  $pids = $pids | Sort-Object -Unique
  foreach ($pid in $pids) {
    Log "[CLEANUP] taskkill /PID $pid /F"
    try { & taskkill /PID $pid /F 2>&1 | Out-Null } catch {}
  }
  if ($pids.Count -gt 0) { Start-Sleep -Seconds 1 }
}

function Wait-BackendHealth {
  param(
    [System.Diagnostics.Process]$Process,
    [string]$HealthUrl,
    [int]$TimeoutSec,
    [string]$HealthFile
  )
  $deadline = (Get-Date).AddSeconds($TimeoutSec)
  $lastStatus = 0
  $lastError = $null
  $content = $null
  while ((Get-Date) -lt $deadline) {
    if ($Process -and $Process.HasExited) {
      $lastError = "process exited with code $($Process.ExitCode)"
      $lastStatus = 0
      break
    }
    try {
      $resp = Invoke-WebRequest -Uri $HealthUrl -UseBasicParsing -TimeoutSec 3
      $lastStatus = $resp.StatusCode
      $content = $resp.Content
      if ($lastStatus -eq 200) {
        if ($HealthFile) {
          $body = if ($null -ne $content) { $content } else { "" }
          Set-Content -Path $HealthFile -Value $body
        }
        return [pscustomobject]@{ Success = $true; Status = $lastStatus; Content = $content }
      }
    } catch {
      $lastError = $_.Exception.Message
      $lastStatus = 0
    }
    Start-Sleep -Milliseconds 250
  }
  if ($HealthFile) {
    $failure = "FAILED STATUS=$lastStatus"
    if ($lastError) { $failure += " ERROR=$lastError" }
    Set-Content -Path $HealthFile -Value $failure
  }
  return [pscustomobject]@{ Success = $false; Status = $lastStatus; Error = $lastError }
}

function Print-BackendLogs([string]$StdoutPath, [string]$StderrPath) {
  foreach ($path in @($StdoutPath, $StderrPath)) {
    $name = Split-Path -Leaf $path
    if (Test-Path $path) {
      Write-Host "----- $name -----"
      Get-Content -LiteralPath $path -ErrorAction SilentlyContinue | ForEach-Object { Write-Host $_ }
      Write-Host "----- end $name -----"
    } else {
      Write-Host "----- $name (missing) -----"
    }
  }
}

function Launch-Backend() {
  Log "[STEP] launch_backend"
  $healthUrl = "http://127.0.0.1:$ApiPort/health"
  Log "[INFO] Resolved API: http://127.0.0.1:$ApiPort."
  Kill-PortBinding $ApiPort
  if (-not (Test-PortFree $ApiPort)) { Log "[WARN] Port $ApiPort still appears in use after cleanup."; Fail 'port_in_use' 1 }

  $backendOut = Join-Path $RUNTIME 'backend.out.log'
  $backendErr = Join-Path $RUNTIME 'backend.err.log'
  Remove-Item -LiteralPath $backendOut -ErrorAction SilentlyContinue
  Remove-Item -LiteralPath $backendErr -ErrorAction SilentlyContinue

  $attempts = @(
    @{ Label = 'python -m backend.server'; Args = @('-m','backend.server') },
    @{ Label = 'uvicorn backend.api:app'; Args = @('-m','uvicorn','backend.api:app','--host','127.0.0.1','--port',"$ApiPort",'--log-level','info') }
  )

  foreach ($attempt in $attempts) {
    Log "[INFO] Starting backend via $($attempt.Label)…"
    $process = Start-Process -FilePath $PYEXE `
      -ArgumentList $attempt.Args `
      -RedirectStandardOutput $backendOut `
      -RedirectStandardError $backendErr `
      -WindowStyle Hidden `
      -PassThru
    Set-Content -Path (Join-Path $RUNTIME 'backend.pid') -Value $process.Id

    $result = Wait-BackendHealth -Process $process -HealthUrl $healthUrl -TimeoutSec 60 -HealthFile (Join-Path $RUNTIME '_health.txt')
    if ($result.Success) {
      Log "[OK] Backend healthy ($($result.Status))."
      return
    }

    Log "[WARN] Backend did not become healthy via $($attempt.Label); status=$($result.Status)."
    try { Stop-Process -Id $process.Id -Force -ErrorAction SilentlyContinue } catch {}
    Start-Sleep -Seconds 2
    Kill-PortBinding $ApiPort
  }

  Log "[ERR] Backend health check failed; printing backend logs before exit."
  Print-BackendLogs -StdoutPath $backendOut -StderrPath $backendErr
  Fail 'backend_health' 1
}

function Launch-UI() {
  Log "[STEP] launch_ui"
  Log "[INFO] Launching Streamlit UI on :$UiPort …"
  $uiOut = Join-Path $RUNTIME 'streamlit.out.log'
  $uiErr = Join-Path $RUNTIME 'streamlit.err.log'
  $streamlitExe = Join-Path $VENV 'Scripts\streamlit.exe'
  $args = @("run","ui\Home.py","--server.port",$UiPort,"--server.headless","true")

  if (Test-Path $streamlitExe) {
    Start-Process -FilePath $streamlitExe -ArgumentList $args -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr -WindowStyle Hidden | Out-Null
  } else {
    Start-Process -FilePath $PYEXE -ArgumentList @("-m","streamlit") + $args -RedirectStandardOutput $uiOut -RedirectStandardError $uiErr -WindowStyle Hidden | Out-Null
  }

  # Poll UI port and open browser on success
  if (Test-UIHealth -timeoutSec 30) {
    Log "[OK] UI is live on :$UiPort"
    Open-UIBrowser
  } else {
    Log "[ERR] UI did not become healthy on :$UiPort within timeout"
    Fail 'ui_health' 1
  }
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
