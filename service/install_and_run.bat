@echo off
echo The legacy pywin32 installer is retired for this deployment.
echo Use Scheduled Tasks as described in ARCHITECTURE_AND_DEPLOYMENT.md.
echo For an existing stopped TEST task, run in elevated PowerShell:
echo   .\configure_task.ps1 -Instance Test
echo   Start-ScheduledTask -TaskName JewelryAgentAPI_Test
echo This script has made no changes.
exit /b 1
