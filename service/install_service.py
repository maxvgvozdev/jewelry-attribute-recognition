"""
Windows service installer helper for Jewelry Agent API.
Usage:
    python install_service.py install
    python install_service.py start
    python install_service.py stop
    python install_service.py remove
"""

import sys
import os
import subprocess
import win32serviceutil
from service.api import SERVICE_NAME


def run(cmd):
    print(f">>> {cmd}")
    subprocess.check_call(cmd, shell=False)


if __name__ == "__main__":
    if len(sys.argv) == 1:
        print("Usage: python install_service.py [install|start|stop|remove]")
        sys.exit(1)

    action = sys.argv[1].lower()
    if action == "install":
        run([sys.executable, "-c", "from service.api import *; print('OK')"])
        run(["python", "-m", "win32serviceutil", "InstallService", SERVICE_NAME])
    elif action in ("start", "stop", "remove"):
        getattr(win32serviceutil, action)(SERVICE_NAME)
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)
