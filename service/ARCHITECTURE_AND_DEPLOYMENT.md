Architecture & Deployment Guide
This document outlines the architecture of the Jewelry Attribute Recognition API and provides instructions for deploying it as a background service on Windows Server 2025.

1. Architecture Overview
The service is a synchronous workflow engine wrapped in a FastAPI REST interface, designed to integrate with Microsoft Business Central.

API Layer: FastAPI + Uvicorn (async endpoints wrapping synchronous heavy-lifting).
Workflow Engine (run_jewelry_workflow): Executes a multi-step pipeline:
Validates provided identifiers (UPC / Vendor Item Number).
Attempts item discovery via a Firecrawl proxy script (if configured) or falls back to direct HTTP requests.
Scrapes resolved product pages for text and image URLs.
Downloads images to the local artifacts/ directory.
Sends images to a Vision Client (service/vision_client.py) for attribute extraction.
Merges text-heuristics and vision results into a standardized 31-parameter attribute payload.
Data Models: Pydantic V2 models strictly validate incoming Business Central payloads and outgoing attribute responses.
2. Windows Server 2025 Deployment Strategy
⚠️ Important: Why We Use Task Scheduler (Not pywin32)
Historically, Python services on Windows were deployed using pywin32 (pythonservice.exe). This is strictly incompatible with Windows Server 2025.

During initial deployment, we discovered that pywin32 fails silently on Server 2025:

It fails to write the required Parameters registry keys (PythonClass, PythonPath, PythonDll).
Even when keys are manually created, pythonservice.exe fails to load the Python DLL and crashes instantly with exit code 0, leaving no Event Viewer logs.
The Solution: We use the native Windows Task Scheduler configured to run at startup under the SYSTEM account. This provides the exact same behavior as a Windows Service (auto-restart, background execution, runs before user login) but is 100% reliable and requires zero third-party C++ binaries.

3. Prerequisites
OS: Windows Server 2025
Python: Python 3.11 (64-bit)
Git: Installed and available in PATH
Permissions: PowerShell run as Administrator
4. Initial Deployment (First-Time Setup)
These steps are only required the very first time you set up the server.

4.1. Clone and Setup Environment
cd C:\Deploygit clone https://github.com/maxvgvozdev/jewelry-attribute-recognition.gitcd jewelry-attribute-recognition\service# Create and activate virtual environmentpython -m venv .venv.\.venv\Scripts\activatepip install -r requirements.txt
4.2. Create Log Directory
The Task Scheduler needs a directory to write application logs.

powershell
New-Item -ItemType Directory -Force -Path "C:\Deploy\jewelry-attribute-recognition\service\logs"

4.3. Register the Scheduled Task
Run this block in an elevated PowerShell to register the API as a background task that auto-starts on boot.

powershell

 $Action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument "/c .venv\Scripts\python.exe api.py >> logs\api.log 2>&1" -WorkingDirectory "C:\Deploy\jewelry-attribute-recognition\service"
 $Trigger = New-ScheduledTaskTrigger -AtStartup
 $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
 $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "JewelryAgentAPI" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Jewelry Attribute Recognition API" -Force
(Note: We use cmd.exe /c with >> to properly route Python's stdout and stderr into a persistent text file, as Task Scheduler does not natively capture console output).

4.4. Start and Verify
powershell

Start-ScheduledTask -TaskName "JewelryAgentAPI"
Start-Sleep -Seconds 3

# Check status
Get-ScheduledTask -TaskName "JewelryAgentAPI" | Select-Object TaskName, State

# Check health endpoint
curl http://localhost:8000/health -UseBasicParsing
5. Ongoing Deployment (Code Updates)
A helper script deploy.ps1 is included in the service/ directory to automate pulling updates from GitHub and restarting the task.

Simply log into the server, open elevated PowerShell, and run:

powershell

cd C:\Deploy\jewelry-attribute-recognition\service
.\deploy.ps1
What it does:

Stops the running task.
Pulls latest code from origin/master.
Restarts the task.
Runs a health check to confirm it came up successfully.
6. Operations & Maintenance
Checking Logs
Because the service runs via cmd.exe, all Python print() and logging statements are routed to a flat file.

powershell

# View last 50 lines of the log
Get-Content C:\Deploy\jewelry-attribute-recognition\service\logs\api.log -Tail 50

# Watch the log in real-time
Get-Content C:\Deploy\jewelry-attribute-recognition\service\logs\api.log -Wait
Tip: If the log file gets too large, you can safely delete api.log while the service is running; it will automatically recreate it on the next log write.

Manually Stopping/Starting
powershell

Stop-ScheduledTask -TaskName "JewelryAgentAPI"
Start-ScheduledTask -TaskName "JewelryAgentAPI"
Uninstalling
To completely remove the background task from the server:

powershell

Stop-ScheduledTask -TaskName "JewelryAgentAPI" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "JewelryAgentAPI" -Confirm:$false
7. Troubleshooting
API returns 500 on /api/jewelry/recognize: Check logs/api.log. This is usually a network timeout to external sites (UPC database, Firecrawl) or a missing dependency in vision_client.py.
Task State is "Ready" but API is unreachable: The Python process likely crashed on startup (e.g., port 8000 already in use, or syntax error in api.py). Check logs/api.log for the Python traceback.
Port 8000 already in use: Find the conflicting process with netstat -ano | findstr :8000 and kill it with taskkill /PID <pid> /F before restarting the task.