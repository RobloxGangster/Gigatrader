[CmdletBinding()]
param(
    [string]$BaseUrl = "http://127.0.0.1:8000",
    [switch]$PlaceTestOrder
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

function Get-IsDryRun {
    $envValue = $env:DRY_RUN
    if ([string]::IsNullOrWhiteSpace($envValue)) {
        return $false
    }
    $normalized = $envValue.Trim().ToLowerInvariant()
    return $normalized -in @('1', 'true', 'yes', 'on')
}

function Test-IsMarketOpen {
    param([string]$Base)
    try {
        $status = Invoke-RestMethod -Uri ($Base + '/orchestrator/status') -TimeoutSec 8
        if ($null -ne $status -and $status.PSObject.Properties.Name -contains 'market_open') {
            if (-not [bool]$status.market_open) {
                Write-Host 'Market closed according to orchestrator/status; skipping test order.'
                return $false
            }
            return [bool]$status.market_open
        }
    } catch {
        Write-Host "orchestrator/status unavailable ($($_.Exception.Message)); proceeding without it."
    }
    return $true
}

function Invoke-TestOrder {
  param([string]$Base)

  $paths = @('/broker/order','/broker/orders')

  # try to learn from openapi
  try {
    $openapi = Invoke-RestMethod -Uri ($Base + '/openapi.json') -TimeoutSec 8
    foreach ($p in $openapi.paths.PSObject.Properties.Name) {
      if ($p -match '/order' -and $openapi.paths.$p.PSObject.Properties.Name -contains 'post') {
        if ($paths -notcontains $p) { $paths += $p }
      }
    }
  } catch {
    Write-Host "openapi lookup failed: $($_.Exception.Message)"
  }

  $body = @{
    symbol = 'AAPL'; qty = 0.01; side = 'buy'; type = 'market'; time_in_force = 'day'
    client_order_id = "gt-sanity-$([guid]::NewGuid().ToString('N').Substring(0,8))"
  } | ConvertTo-Json

  foreach ($p in $paths) {
    try {
      $u = $Base + $p
      Write-Host "POST $p (test)"
      $res = Invoke-RestMethod -Method Post -Uri $u -Body $body -ContentType 'application/json' -TimeoutSec 15
      $res | ConvertTo-Json -Depth 10
      return
    } catch {
      Write-Host "  FAILED: $($_.Exception.Message)"
    }
  }
  throw "No working order endpoint found (tried: $($paths -join ', '))"
}

if ($PlaceTestOrder) {
    if (Get-IsDryRun) {
        Write-Host 'DRY_RUN is enabled; skipping live order test.'
    } elseif (Test-IsMarketOpen -Base $BaseUrl) {
        Invoke-TestOrder -Base $BaseUrl
    } else {
        Write-Host 'Skipping test order because market is closed.'
    }
}
