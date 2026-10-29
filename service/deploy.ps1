# Run from the intended instance checkout in an elevated PowerShell.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
Get-ScheduledTask -TaskName "JewelryAgentAPI" -ErrorAction Stop | Out-Null
$dirty = git status --porcelain
if ($LASTEXITCODE -ne 0) { throw "Cannot inspect Git working tree." }
if ($dirty) { throw "Working tree has local changes. Review them before deployment." }
$branch = git branch --show-current
if ($LASTEXITCODE -ne 0 -or $branch -ne "master") { throw "Deployment requires branch master." }
# Fetch/update before interrupting the running API.
git pull --ff-only origin master
if ($LASTEXITCODE -ne 0) { throw "Git update failed; scheduled task was not stopped." }

Stop-ScheduledTask -TaskName "JewelryAgentAPI" -ErrorAction Stop
Start-Sleep -Seconds 2
& (Join-Path $PSScriptRoot "configure_task.ps1") -Instance Live
Start-ScheduledTask -TaskName "JewelryAgentAPI"
$healthy = $false
for ($attempt = 0; $attempt -lt 10; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri "http://127.0.0.1:8000/health" -TimeoutSec 3
        $healthy = $true
        break
    } catch { }
}
if (-not $healthy) { throw "API health check failed. Inspect logs/api.log. No automatic rollback was performed." }
Get-ScheduledTask -TaskName "JewelryAgentAPI" | Select-Object TaskName, State
$health
Write-Host "API responds on 8000. This does not verify Vision inference or Business Central."
