Architecture & Deployment Guide
This document outlines the architecture of the Jewelry & Watch Attribute Recognition API and provides instructions for deploying it as a background service on Windows Server 2025.

1. Architecture Overview
The service is a synchronous workflow engine wrapped in a FastAPI REST interface, designed to integrate with Microsoft Business Central via a 2-step process (Invoice Parsing -> Item Enrichment).

API Layer: FastAPI + Uvicorn (async endpoints wrapping synchronous heavy-lifting).
Category Routing: api.py routes logic based on a category field (jewelry or watch). This determines which Pydantic model, Vision prompt, and BC365 validation map is used.
Workflow Engine (run_jewelry_workflow): Executes a multi-step pipeline:
Validates provided identifiers (UPC / Vendor Item Number).
Attempts item discovery via a Firecrawl proxy script or falls back to direct HTTP requests.
Scrapes resolved product pages for text and image URLs.
Downloads images to the local artifacts/ directory.
Sends images to a Vision Client (service/vision_client.py) for attribute extraction. Forces "format": "json" to prevent LLM rambling.
Merges text-heuristics and Vision AI results. Includes a smart JSON repair function (_extract_json_from_text) to fix truncated LLM outputs.
Data Models: Pydantic V2 models strictly validate incoming Business Central payloads and outgoing attribute responses (31 Jewelry attributes or 40+ Watch attributes).
2. Dual-Instance Architecture (Server Setup)
To develop new features safely without breaking the live Business Central integration, the Windows Server runs two isolated instances of the service simultaneously:

Production Instance:
Folder: C:\Deploy\jewelry-attribute-recognition\service
Port: 8000
Script: deploy.ps1
Task Name: JewelryAgentAPI
Test Instance:
Folder: C:\Deploy\jewelry-attribute-recognition-test\service
Port: 8001
Script: deploy_test.ps1
Task Name: JewelryAgentAPI_Test
3. Windows Server 2025 Deployment Strategy
⚠️ Important: Why We Use Task Scheduler (Not pywin32)

Historically, Python services on Windows were deployed using pywin32 (pythonservice.exe). This is strictly incompatible with Windows Server 2025.

During initial deployment, we discovered that pywin32 fails silently on Server 2025:

It fails to write the required Parameters registry keys (PythonClass, PythonPath, PythonDll).
Even when keys are manually created, pythonservice.exe fails to load the Python DLL and crashes instantly with exit code 0, leaving no Event Viewer logs.
The Solution: We use the native Windows Task Scheduler configured to run at startup under the SYSTEM account. This provides the exact same behavior as a Windows Service (auto-restart, background execution, runs before user login) but is 100% reliable and requires zero third-party C++ binaries.

4. Prerequisites
OS: Windows Server 2025
Python: Python 3.11 (64-bit)
Git: Installed and available in PATH
Permissions: PowerShell run as Administrator
5. Initial Deployment (First-Time Setup)
These steps are only required the very first time you set up the server. Below is the setup for the Test Instance. Repeat for Production, swapping -test and _Test with the production equivalents, and setting the port to 8000.

5.1. Clone and Setup Environment
cd C:\Deploygit clone https://github.com/maxvgvozdev/jewelry-attribute-recognition.git jewelry-attribute-recognition-testcd jewelry-attribute-recognition-test\service# Create and activate virtual environmentpython -m venv .venv.\.venv\Scripts\activatepip install -r requirements.txt
5.2. Create Log Directory
The Task Scheduler needs a directory to write application logs.

powershell

New-Item -ItemType Directory -Force -Path "C:\Deploy\jewelry-attribute-recognition-test\service\logs"
5.3. Register the Scheduled Task
Run this block in an elevated PowerShell to register the API as a background task that auto-starts on boot. Note the set JEWELRY_API_PORT=8001 which forces the test instance to use the correct port.

powershell

 $Action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument "/c set JEWELRY_API_PORT=8001 && .venv\Scripts\python.exe api.py >> logs\api.log 2>&1" `
    -WorkingDirectory "C:\Deploy\jewelry-attribute-recognition-test\service"

 $Trigger = New-ScheduledTaskTrigger -AtStartup
 $Principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -LogonType ServiceAccount -RunLevel Highest
 $Settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -DontStopOnIdleEnd -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1)

Register-ScheduledTask -TaskName "JewelryAgentAPI_Test" -Action $Action -Trigger $Trigger -Principal $Principal -Settings $Settings -Description "Jewelry Attribute Recognition API (Test)" -Force
(Note: We use cmd.exe /c with >> to properly route Python's stdout and stderr into a persistent text file, as Task Scheduler does not natively capture console output).

Important: When editing the task in Task Scheduler, ensure the "Start in (optional)" field is explicitly set to C:\Deploy\jewelry-attribute-recognition-test\service. If this is blank, the service will start in C:\Windows\System32 and fail to find your code.

5.4. Start and Verify
powershell

Start-ScheduledTask -TaskName "JewelryAgentAPI_Test"
Start-Sleep -Seconds 3

# Check status
Get-ScheduledTask -TaskName "JewelryAgentAPI_Test" | Select-Object TaskName, State

# Check health endpoint
curl http://localhost:8001/health -UseBasicParsing
6. Ongoing Deployment (Code Updates)
Helper scripts (deploy.ps1 and deploy_test.ps1) are included in the service/ directory to automate pulling updates from GitHub and restarting the task.

To deploy to the Test Instance:

powershell

cd C:\Deploy\jewelry-attribute-recognition-test\service
.\deploy_test.ps1
To deploy to the Production Instance:

powershell

cd C:\Deploy\jewelry-attribute-recognition\service
.\deploy.ps1
What the script does:

Stops the running task.
Pulls latest code from origin/master.
Restarts the task.
Runs a health check to confirm it came up successfully.
7. Operations & Maintenance
Checking Logs
Because the service runs via cmd.exe, all Python print() and logging statements are routed to a flat file.

powershell

# View last 50 lines of the log (Test Instance)
Get-Content C:\Deploy\jewelry-attribute-recognition-test\service\logs\api.log -Tail 50

# Watch the log in real-time
Get-Content C:\Deploy\jewelry-attribute-recognition-test\service\logs\api.log -Wait
Tip: If the log file gets too large, you can safely delete api.log while the service is running; it will automatically recreate it on the next log write.

Manually Stopping/Starting
powershell

Stop-ScheduledTask -TaskName "JewelryAgentAPI_Test"
Start-ScheduledTask -TaskName "JewelryAgentAPI_Test"
Uninstalling
To completely remove the background task from the server:

powershell

Stop-ScheduledTask -TaskName "JewelryAgentAPI_Test" -ErrorAction SilentlyContinue
Unregister-ScheduledTask -TaskName "JewelryAgentAPI_Test" -Confirm:$false
8. Troubleshooting
Swagger UI says "Failed to fetch" (CORS error): This is usually a false alarm. It means the API crashed while processing your request. Check logs/api.log for a Python Traceback. You can also bypass Swagger by running the API manually: cd C:\Deploy\jewelry-attribute-recognition-test\service, set $env:JEWELRY_API_PORT="8001", and run python api.py to see errors print directly to the console.
Vision AI returns null for all image attributes: The Vision AI prompt may have been truncated due to token limits. Ensure vision_client.py has num_ctx: 8192 and num_predict: 2048. We also rely on _extract_json_from_text in api.py to repair truncated JSON outputs.
API returns 500 on /api/jewelry/recognize: Check logs/api.log. This is usually a network timeout to external sites (UPC database, Firecrawl) or a missing dependency in vision_client.py.
Task State is "Ready" but API is unreachable: The Python process likely crashed on startup (e.g., port already in use, or syntax error in api.py). Check logs/api.log for the Python traceback.
Port already in use: Find the conflicting process with netstat -ano | findstr :8001 (or 8000) and kill it with taskkill /PID <pid> /F before restarting the task.
API times out on /api/jewelry/recognize with a local network error: Ensure Tailscale is connected and running on the Windows Server. Run Test-NetConnection -ComputerName 100.88.93.128 -Port 11434. If this fails, the API cannot reach the local Vision AI on the Spark machine.
