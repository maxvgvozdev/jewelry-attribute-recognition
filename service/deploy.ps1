# deploy.ps1 - Run this on the server to pull updates and restart the service
 $ErrorActionPreference = "Stop"

Write-Host "1. Stopping existing service..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe api.py stop 2>$null

Write-Host "2. Pulling latest code from GitHub..." -ForegroundColor Cyan
git pull origin master

Write-Host "3. Removing old service registration (to sync registry)..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe api.py remove 2>$null

Write-Host "4. Installing service..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe api.py install

Write-Host "5. Starting service..." -ForegroundColor Cyan
.\.venv\Scripts\python.exe api.py start

Write-Host "6. Waiting for startup..." -ForegroundColor Cyan
Start-Sleep -Seconds 5

Write-Host "Final Service Status:" -ForegroundColor Green
sc.exe query JewelryAgentAPI