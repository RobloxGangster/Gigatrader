$TLOG = Join-Path (Join-Path $PSScriptRoot '..') 'logs\tests'
Get-ChildItem -Path $TLOG -Filter '*.log' | Sort-Object LastWriteTime -Descending | Select-Object -First 1 | ForEach-Object {
  Write-Host "Last test log: $($_.FullName)`n"
  Get-Content -Tail 50 -Path $_.FullName
}
Read-Host "[Press Enter to close]"
