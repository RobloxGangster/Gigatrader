# requires -Version 5.1
$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Write-Status {
    param(
        [string]$Message,
        [ValidateSet('Info','Warn','Error')]
        [string]$Level = 'Info'
    )

    $timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
    switch ($Level) {
        'Info'  { $color = 'Cyan';   $icon = '[+]' }
        'Warn'  { $color = 'Yellow'; $icon = '[!]' }
        'Error' { $color = 'Red';    $icon = '[-]' }
    }

    Write-Host "${timestamp} ${icon} $Message" -ForegroundColor $color
}

function Exit-WithError {
    param([string]$Message, [int]$Code = 1)
    Write-Status $Message 'Error'
    exit $Code
}

Write-Status 'Starting Gigatrader environment installation.'

# Resolve repository root based on script location to allow execution from any working directory.
$scriptPath = Resolve-Path -LiteralPath $MyInvocation.MyCommand.Path
$scriptDir  = Split-Path -Parent $scriptPath
$repoRoot   = Split-Path -Parent $scriptDir
Write-Status "Resolved repository root to '$repoRoot'."

# Step 1: Ensure execution policy allows running this script.
$effectivePolicy = Get-ExecutionPolicy
if ($effectivePolicy -in @('Restricted', 'AllSigned')) {
    Write-Status "Current execution policy '$effectivePolicy' prevents running unsigned scripts." 'Error'
    Write-Host "Please re-run this installer in an elevated PowerShell session and execute:" -ForegroundColor Yellow
    Write-Host "    Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser" -ForegroundColor Yellow
    Exit-WithError 'Execution policy is too restrictive. Installation aborted.'
}
Write-Status "Execution policy '$effectivePolicy' is acceptable."

# Step 2: Locate Python 3.11 interpreter.
function Get-Python311 {
    $pythonExe = $null
    $version = $null

    try {
        $output = & py -3.11 -c "import sys;print(sys.executable);print('.'.join(map(str, sys.version_info[:3])))" 2>$null
        if ($LASTEXITCODE -eq 0 -and $output) {
            $pythonExe = $output[0].Trim()
            $version = $output[1].Trim()
        }
    } catch {
        # Ignore and fall back to python.exe discovery below.
    }

    if (-not $pythonExe) {
        try {
            $output = & python -c "import sys;print(sys.executable);print('.'.join(map(str, sys.version_info[:3])))" 2>$null
            if ($LASTEXITCODE -eq 0 -and $output) {
                $pythonExe = $output[0].Trim()
                $version = $output[1].Trim()
            }
        } catch {
            # No python command available.
        }
    }

    if (-not $pythonExe) {
        return $null
    }

    return @{ Path = $pythonExe; Version = $version }
}

$pythonInfo = Get-Python311
if (-not $pythonInfo) {
    Write-Host ''
    Write-Host 'Python 3.11 could not be located.' -ForegroundColor Red
    Write-Host 'Please install Python 3.11 from https://www.python.org/downloads/windows/ and ensure it is added to PATH or the py launcher is available.' -ForegroundColor Yellow
    Exit-WithError 'Python 3.11 is required.'
}

$pythonVersion = [version]$pythonInfo.Version
if ($pythonVersion.Major -ne 3 -or $pythonVersion.Minor -lt 11) {
    Write-Host "Detected Python version $($pythonInfo.Version) at '$($pythonInfo.Path)' which does not meet the >=3.11 requirement." -ForegroundColor Red
    Write-Host 'Download and install Python 3.11 from https://www.python.org/downloads/windows/.' -ForegroundColor Yellow
    Exit-WithError 'Python 3.11 is required for Gigatrader.'
}

Write-Status "Using Python $($pythonInfo.Version) at '$($pythonInfo.Path)'."

# Step 3: Create or reuse the .venv virtual environment.
$venvPath = Join-Path $repoRoot '.venv'
$venvScriptsPath = Join-Path $venvPath 'Scripts'
$venvPython = Join-Path $venvScriptsPath 'python.exe'

if (-not (Test-Path -LiteralPath $venvPython)) {
    Write-Status "Creating virtual environment at '$venvPath'."
    & $pythonInfo.Path -m venv $venvPath
} else {
    Write-Status "Reusing existing virtual environment at '$venvPath'."
}

# Verify the venv Python version to guard against stale environments.
$venvVersionOutput = & $venvPython -c "import sys;print('.'.join(map(str, sys.version_info[:3])))"
$venvVersion = [version]$venvVersionOutput.Trim()
if ($venvVersion.Major -ne 3 -or $venvVersion.Minor -lt 11) {
    Write-Status "Existing virtual environment uses Python $venvVersionOutput which is incompatible. Recreating." 'Warn'
    Remove-Item -LiteralPath $venvPath -Recurse -Force
    & $pythonInfo.Path -m venv $venvPath
    $venvVersionOutput = & $venvPython -c "import sys;print('.'.join(map(str, sys.version_info[:3])))"
    $venvVersion = [version]$venvVersionOutput.Trim()
}
Write-Status "Virtual environment ready with Python $venvVersionOutput."

# Ensure Scripts path is at the front of PATH for subsequent commands.
$originalPath = $env:PATH
$env:PATH = "$venvScriptsPath;$originalPath"
$env:VIRTUAL_ENV = $venvPath

# Step 4: Upgrade packaging tooling and install dependencies.
$requirementsPath = Join-Path $repoRoot 'requirements.txt'
if (-not (Test-Path -LiteralPath $requirementsPath)) {
    $env:PATH = $originalPath
    Remove-Variable VIRTUAL_ENV -ErrorAction SilentlyContinue
    Exit-WithError "requirements.txt was not found at '$requirementsPath'. If you are offline, please ensure the file is present before retrying."
}

Write-Status 'Upgrading pip, setuptools, and wheel.'
& $venvPython -m pip install --upgrade pip setuptools wheel

Write-Status "Installing Python dependencies from '$requirementsPath'."
& $venvPython -m pip install --upgrade -r $requirementsPath

# Step 5 & 6: Ensure configuration templates are copied if missing.
$envExamplePath = Join-Path $repoRoot '.env.example'
$envPath = Join-Path $repoRoot '.env'
if (Test-Path -LiteralPath $envExamplePath -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $envPath)) {
        Write-Status 'Creating .env from .env.example.'
        Copy-Item -LiteralPath $envExamplePath -Destination $envPath
    } else {
        Write-Status '.env already exists. Leaving as-is.'
    }
} else {
    Write-Status '.env.example not found; please create .env manually.' 'Warn'
}

$configExamplePath = Join-Path $repoRoot 'config.example.yaml'
$configPath = Join-Path $repoRoot 'config.yaml'
if (Test-Path -LiteralPath $configExamplePath -PathType Leaf) {
    if (-not (Test-Path -LiteralPath $configPath)) {
        Write-Status 'Creating config.yaml from config.example.yaml.'
        Copy-Item -LiteralPath $configExamplePath -Destination $configPath
    } else {
        Write-Status 'config.yaml already exists. Leaving as-is.'
    }
} else {
    Write-Status 'config.example.yaml not found; please create config.yaml manually.' 'Warn'
}

# Step 7: Validate required environment keys.
$missingKeys = @()
if (Test-Path -LiteralPath $envPath) {
    $envContent = Get-Content -LiteralPath $envPath
    foreach ($key in 'ALPACA_API_KEY','ALPACA_API_SECRET','ALPACA_BASE_URL') {
        if (-not ($envContent -match "^\s*$key\s*=")) {
            $missingKeys += $key
        }
    }

    if ($missingKeys.Count -gt 0) {
        Write-Status 'Some required Alpaca environment variables are missing from .env.' 'Warn'
        foreach ($key in $missingKeys) {
            Write-Host "    • TODO: Add $key=... to .env (see .env.example for guidance)." -ForegroundColor Yellow
        }
    } else {
        Write-Status 'All required Alpaca environment variables are present in .env.'
    }
} else {
    Write-Status '.env not found. Trading commands will prompt for credentials later.' 'Warn'
}

# Step 8: Provide CLI availability diagnostics.
$tradeExe = Join-Path $venvScriptsPath 'trade.exe'
$hasTrade = Test-Path -LiteralPath $tradeExe
$canImportApp = $false
try {
    & $venvPython -c "import app, sys; print('ok')" > $null
    if ($LASTEXITCODE -eq 0) { $canImportApp = $true }
} catch {
    $canImportApp = $false
}

if (-not $hasTrade -and -not $canImportApp) {
    Write-Status 'Neither the trade console script nor app CLI module could be detected. Collecting diagnostics.' 'Warn'
    Write-Host '--- pip list ----------------------------------------------------' -ForegroundColor DarkGray
    & $venvPython -m pip list
    Write-Host '--- where trade --------------------------------------------------' -ForegroundColor DarkGray
    try {
        & cmd.exe /c 'where trade' 2>&1
    } catch {
        Write-Host $_ -ForegroundColor Red
    }
    Write-Host '--- python -c "import app" --------------------------------------' -ForegroundColor DarkGray
    try {
        & $venvPython -c "import app, sys; print('ok')"
    } catch {
        Write-Host $_ -ForegroundColor Red
    }
} else {
    if ($hasTrade) { Write-Status "CLI entry point 'trade' detected at '$tradeExe'." }
    if ($canImportApp) { Write-Status 'Python module app.cli import test succeeded.' }
}

# Step 9: Print next steps.
Write-Host ''
Write-Status 'Installation complete! Next steps:'
Write-Host "    scripts\\run_paper.bat" -ForegroundColor Green
Write-Host "    scripts\\run_backtest.bat" -ForegroundColor Green
Write-Host ''
Write-Status 'Remember: Live trading requires LIVE_TRADING=true and scripts\run_live.bat.' 'Warn'

# Restore PATH and exit successfully.
$env:PATH = $originalPath
Remove-Variable VIRTUAL_ENV -ErrorAction SilentlyContinue

Write-Status 'Setup finished successfully.'
exit 0

# Smoke test:
#   powershell -ExecutionPolicy Bypass -File scripts/install.ps1
