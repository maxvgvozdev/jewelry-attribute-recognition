# deploy.ps1 - Run this on the server to pull updates and restart the service
 $ErrorActionPreference = "Stop"

Write-Host "1. Stopping existing scheduled task..." -ForegroundColor Cyan
Stop-ScheduledTask -TaskName "JewelryAgentAPI" -ErrorAction SilentlyContinue

Write-Host "2. Pulling latest code from GitHub..." -ForegroundColor Cyan
git pull origin master

Write-Host "3. Waiting for process to fully exit..." -ForegroundColor Cyan
Start-Sleep -Seconds 2

Write-Host "4. Starting scheduled task..." -ForegroundColor Cyan
Start-ScheduledTask -TaskName "JewelryAgentAPI"

Write-Host "5. Waiting for startup..." -ForegroundColor Cyan
Start-Sleep -Seconds 4

Write-Host "Final Service Status:" -ForegroundColor Green
Get-ScheduledTask -TaskName "JewelryAgentAPI" | Select-Object TaskName, State

Write-Host "Health Check:" -ForegroundColor Green
try {
    $health = Invoke-RestMethod -Uri "http://localhost:8000/health" -UseBasicParsing -TimeoutSec 5
    Write-Host $health -ForegroundColor Green
} catch {
    Write-Host "API not responding yet." -ForegroundColor Yellow
}