# Jewelry Attribute Recognition API – Deployment Guide

## Overview

Expose jewelry attribute recognition to **Microsoft Business Central** via a
REST API running on **Windows Server 2025** as a Windows service.

- Base path: `http://<host>:8000`
- Endpoint: `POST /api/jewelry/recognize`
- Input: JSON payload with `brand`, `vendor_item_number`, `upc_code`, `source_url`
- Output: 31-parameter jewelry recognition JSON

## Prerequisites

- Windows Server 2025
- Python 3.11+
- Git (optional, for pulling latest skill code)
- Network access from Business Central host to this server on TCP 8000
- Firewall rule allowing inbound TCP 8000 (or your chosen port)

## Quick Install (interactive)

```powershell
cd C:\Deploy\jewelry-attribute-recognition\service

# 1) create virtualenv
python -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2) install deps
pip install -r requirements.txt

# 3) copy the skill root into place
#    xcopy /E /I .. C:\Skills\jewelry-attribute-recognition

# 4) install Windows service
python install_service.py install

# 5) start service
python install_service.py start
```

Verify:

```powershell
curl http://localhost:8000/health
# {"status":"ok","service":"JewelryAgentAPI"}
```

## Server deploy checklist

```powershell
cd C:\Deploy\jewelry-attribute-recognition

# 1) pull latest changes
git pull origin master

# 2) reinstall and restart service
cd service
.\\.venv\Scripts\python.exe install_service.py install
.\\.venv\Scripts\python.exe install_service.py start

# 3) verify
sc query JewelryAgentAPI
curl http://localhost:8000/health
```

## Production deployment notes

- Set env vars via System Properties → Advanced → Environment Variables:
  - `JEWELRY_API_PORT=8000`
  - `JEWELRY_API_LOG_LEVEL=INFO`
- Ensure `firecrawl_config.json` is present under the skill root if Firecrawl is required.
- The service auto-restarts with Windows.

## Business Central integration

Business Central can call the API using standard `HttpClient` or `WebService`.

Example body for `POST /api/jewelry/recognize`:

```json
{
  "brand": "David Yurman",
  "vendor_item_number": "B18729D88APRDIM",
  "upc_code": "192740580147",
  "source_url": "https://www.davidyurman.com/"
}
```

PowerShell test from Business Central host or AL code:

```powershell
Invoke-RestMethod -Method Post -Uri http://<server>:8000/api/jewelry/recognize `
  -ContentType "application/json" `
  -Body '{"brand":"David Yurman","vendor_item_number":"B18729D88APRDIM","upc_code":"192740580147","source_url":"https://www.davidyurman.com/"}'
```

## Troubleshooting

- If port 8000 isn’t reachable, open it in Windows Defender Firewall.
- If the service fails to start, run `python service_runner.py` interactively to view traceback.
- Verify `firecrawl_config.json` exists if item lookup fails silently.
