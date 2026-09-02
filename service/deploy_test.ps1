# deploy_test.ps1 - Run this on the server to update the TEST instance
 $ErrorActionPreference = "Stop"

Write-Host "1. Stopping existing TEST scheduled task..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "JewelryAgentAPI_Test" -ErrorAction SilentlyContinue | Out-Null

Write-Host "2. Pulling latest code from GitHub..." -ForegroundColor Cyan
git pull origin master

Write-Host "3. Waiting for process to fully exit..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

Write-Host "4. Starting TEST scheduled task..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "JewelryAgentAPI_Test" | Out-Null

Write-Host "5. Waiting for startup..." -ForegroundColor Cyan
Start-Sleep -Seconds 4

Write-Host "Final Service Status:" -ForegroundColor Green
Get-ScheduledTask -TaskName "JewelryAgentAPI_Test" | Select-Object TaskName, State

Write-Host "Health Check (Port 8001):" -ForegroundColor Green
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8001/health" -UseBasicParsing -TimeoutSec 5
    Write-Host $health -ForegroundColor Green
} catch {
    Write-Host "API not responding yet." -ForegroundColor Yellow
}
