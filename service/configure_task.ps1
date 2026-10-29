param(
    [ValidateSet("Test", "Live")]
    [string]$Instance = "Test"
)
$ErrorActionPreference = "Stop"
$taskName = if ($Instance -eq "Test") { "JewelryAgentAPI_Test" } else { "JewelryAgentAPI" }
$port = if ($Instance -eq "Test") { 8001 } else { 8000 }
$task = Get-ScheduledTask -TaskName $taskName -ErrorAction Stop
if ($task.Actions.Count -ne 1) { throw "Expected one task action; inspect the task manually." }
$existingDirectory = $task.Actions[0].WorkingDirectory
if (-not $existingDirectory -or
    [IO.Path]::GetFullPath($existingDirectory).TrimEnd('\\') -ne
    [IO.Path]::GetFullPath($PSScriptRoot).TrimEnd('\\')) {
    throw "Run this script from the existing task's WorkingDirectory."
}
if ($task.State -eq "Running") {
    throw "Stop $taskName in an agreed maintenance window before changing its action."
}
if (-not (Test-Path (Join-Path $PSScriptRoot "start_api.cmd"))) {
    throw "start_api.cmd is missing."
}
New-Item -ItemType Directory -Force -Path (Join-Path $PSScriptRoot "logs") | Out-Null
$backup = Join-Path $PSScriptRoot ("logs\{0}-{1}.xml" -f $taskName, (Get-Date -Format "yyyyMMdd-HHmmssfff"))
Export-ScheduledTask -TaskName $taskName | Set-Content -LiteralPath $backup -Encoding Unicode
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" `
    -Argument ('/d /c ""{0}" {1}"' -f (Join-Path $PSScriptRoot "start_api.cmd"), $port) `
    -WorkingDirectory $PSScriptRoot
Set-ScheduledTask -TaskName $taskName -Action $action | Out-Null
Write-Host "Updated $taskName action; task has NOT been started. Backup: $backup"
