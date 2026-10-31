# Launch SettlementLens Merchant Dashboard
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location (Join-Path $ScriptDir "..")
Write-Host "========================================================" -ForegroundColor Cyan
Write-Host "Starting SettlementLens Merchant Interface..." -ForegroundColor Green
Write-Host "========================================================" -ForegroundColor Cyan
python -m gui.app
