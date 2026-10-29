Architecture & Deployment Guide
This document outlines the architecture of the Jewelry & Watch Attribute Recognition API and provides instructions for deploying it as a background service on Windows Server 2025.

1. Architecture Overview
The service is a synchronous workflow engine wrapped in a FastAPI REST interface, designed to integrate with Microsoft Business Central via a 2-step process (Invoice Parsing -> Item Enrichment).

API Layer: FastAPI + Uvicorn; the main POST handlers use synchronous def functions.
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

Historically, Python services on Windows were deployed using pywin32 (pythonservice.exe). The previous pywin32 installation failed on this server; this is a deployment-specific observation, not a general compatibility claim.

During initial deployment, we discovered that pywin32 fails silently on Server 2025:

It fails to write the required Parameters registry keys (PythonClass, PythonPath, PythonDll).
Even when keys are manually created, pythonservice.exe fails to load the Python DLL and crashes instantly with exit code 0, leaving no Event Viewer logs.
The Solution: We use the native Windows Task Scheduler configured to run at startup under the SYSTEM account. This provides the exact same behavior as a Windows Service (auto-restart, background execution, runs before user login) without using the previous pythonservice.exe wrapper. Startup and recovery still require validation.

4. Prerequisites
OS: Windows Server 2025
Python: Python 3.11 (64-bit)
Git: Installed and available in PATH
Permissions: PowerShell run as Administrator
5. Initial Deployment (First-Time Setup)
These steps are only required the very first time you set up the server. Below is the setup for the Test Instance. Repeat for Production, swapping -test and _Test with the production equivalents, and setting the port to 8000.

5.1. Clone and Setup Environment
```powershell
cd C:\Deploy
git clone https://github.com/maxvgvozdev/jewelry-attribute-recognition.git jewelry-attribute-recognition-test
cd jewelry-attribute-recognition-test\service
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```
5.2. Create Log Directory
The Task Scheduler needs a directory to write application logs.

powershell

New-Item -ItemType Directory -Force -Path "C:\Deploy\jewelry-attribute-recognition-test\service\logs"
5.3. Register the Scheduled Task
Run this block in an elevated PowerShell to register the API as a background task that auto-starts on boot. The launcher sets port 8001 and the Spark VPN URL explicitly.

powershell

 $Action = New-ScheduledTaskAction -Execute "cmd.exe" `
    -Argument '/d /c ""C:\Deploy\jewelry-attribute-recognition-test\service\start_api.cmd" 8001"' `
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

Checks for a clean master checkout and pulls with --ff-only before stopping the task.
Stops the selected task and updates only its launch action (with an XML backup).
Restarts via start_api.cmd with an explicit instance port and VPN URL.
Fails if the API health check does not pass. There is no automatic rollback; /health does not verify Vision inference.
7. Operations & Maintenance
Checking Logs
Because the service runs via cmd.exe, all Python print() and logging statements are routed to a flat file.

powershell

# View last 50 lines of the log (Test Instance)
Get-Content C:\Deploy\jewelry-attribute-recognition-test\service\logs\api.log -Tail 50

# Watch the log in real-time
Get-Content C:\Deploy\jewelry-attribute-recognition-test\service\logs\api.log -Wait
Stop the task before rotating api.log, then restart it. Do not delete an open log file.

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
API times out on /api/jewelry/recognize with a local network error: Check the administrator-managed VPN. Run Test-NetConnection -ComputerName 10.77.0.2 -Port 11434. If this fails, the API cannot reach the local Vision AI on the Spark machine.


## VPN migration (2026-10-29)

All source changes are committed to GitHub first and pulled to the server before use.
The administrator-managed encrypted VPN replaces Tailscale for Windows API -> Spark.
Windows VPN IP: 10.77.0.1; Spark VPN IP: 10.77.0.2. The reported /32 settings must be interpreted as host routes, not a shared two-host subnet; routing is managed by the administrator.

- Spark base URL: http://10.77.0.2:11434. HTTP is used inside the encrypted VPN; HTTPS is not part of this migration.
- Restrict Spark port 11434 to the intended API host via the VPN; do not expose Ollama publicly.
- BC and API are planned to share the company server. Use http://127.0.0.1:8000 when BC executes in the same host network. Containers require a separate addressing decision.
- Keep the current API bind setting during testing. On the company server, bind to loopback only if no remote clients require access.
- Keep existing VISION_MODEL, VISION_PROVIDER and credentials. The current Python default is default:latest, but environment overrides still apply.
- start_api.cmd explicitly sets VISION_API_URL and JEWELRY_API_PORT for the child process. A changed Machine environment variable alone does not prove a running task uses the new address.

Confirmed: TCP connectivity and Ollama /api/tags over the Spark interface; default:latest returned CONNECTION_OK via /api/generate. Image inference, BC end-to-end processing, operation without Tailscale and reboot recovery remain unverified.

Observed tasks before migration: JewelryAgentAPI is Running with direct python.exe api.py; JewelryAgentAPI_Test is Ready with cmd.exe and no explicit port. Ready means it is not currently running. The legacy stopped Windows service is not the active API launcher. Do not use Start-Service for this deployment.

### Migrate the existing test task first

In elevated PowerShell, from the test checkout:

```powershell
cd C:\Deploy\jewelry-attribute-recognition-test\service
git status --short
git pull --ff-only origin master
# Stop if either Git command fails or local changes require reconciliation.
.\configure_task.ps1 -Instance Test
Start-ScheduledTask -TaskName JewelryAgentAPI_Test
Get-Content .\logs\api.log -Tail 50
Invoke-RestMethod http://127.0.0.1:8001/health
```

configure_task.ps1 requires the task to be stopped, backs up its XML in logs, preserves its principal/triggers/settings, changes only its action, and does not start it. Never point the test task at the live checkout. For a new server, first register the task using section 5 with the appropriate directory and port.

Check startup logs and perform both invoice parsing and item enrichment with known samples. Confirm the Vision call targets 10.77.0.2. During an administrator-coordinated test, disable Tailscale and repeat the request. Verify firewall restrictions and VPN/task recovery after reboot before approving migration to the company server.

Only after test validation, update the live checkout and run deploy.ps1 in a maintenance window. The folder called Production in this document is the current BC-connected instance on the existing server; it does not mean migration to the company server is complete.

Rollback: stop the affected task, restore its exported XML using Register-ScheduledTask -Xml (Get-Content <backup.xml> -Raw) -TaskName <task-name> -Force, and restart it. Retain the original Machine environment value and Tailscale until validation is complete. Restoring the task does not restore code or changed Machine variables; restore those separately if required. Do not delete the legacy service during this transition.
