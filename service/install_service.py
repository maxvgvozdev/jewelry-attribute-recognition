import sys
import pathlib
import subprocess
import os
import win32serviceutil
import win32service

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHONPATH = f"{REPO_ROOT};{os.environ.get('PYTHONPATH', '')}".strip(";")
sys.path.insert(0, str(REPO_ROOT))

from service.api import SERVICE_NAME, SERVICE_DISPLAY_NAME, SERVICE_DESCRIPTION, JewelryAPIService


def _ensure_repo_root_on_sys_path() -> None:
    pth = pathlib.Path(sys.executable).resolve().parent.parent / "Lib" / "site-packages" / "repo_root.pth"
    if not pth.exists():
        pth.write_text(str(REPO_ROOT) + "\n", encoding="utf-8")

def _get_pythonservice_exe() -> str:
    """Determine the correct path to pythonservice.exe in the venv."""
    venv_root = pathlib.Path(sys.executable).resolve().parent.parent
    exe_path = venv_root / "pythonservice.exe"
    if not exe_path.exists():
        exe_path = pathlib.Path(win32service.__file__).parent / "pythonservice.exe"
    return str(exe_path)

def run(cmd, extra_env=None):
    env = os.environ.copy()
    env["PYTHONPATH"] = PYTHONPATH
    if extra_env:
        env.update(extra_env)
    print('>>> ' + str(cmd))
    subprocess.check_call(cmd, shell=False, env=env)


if __name__ == '__main__':
    if len(sys.argv) == 1:
        print('Usage: python service/install_service.py [install|start|stop|remove]')
        sys.exit(1)

    action = sys.argv[1].lower()
    if action == 'install':
        print('Installing service', SERVICE_NAME)
        _ensure_repo_root_on_sys_path()
        win32serviceutil.InstallService(
            pythonClassString='service.api.JewelryAPIService',
            serviceName=SERVICE_NAME,
            displayName=SERVICE_DISPLAY_NAME,
            description=SERVICE_DESCRIPTION,
            startType=win32service.SERVICE_AUTO_START,
            exeName=_get_pythonservice_exe(),  # <-- THIS WAS MISSING
        )
    elif action in ('start', 'stop', 'remove'):
        win32serviceutil.HandleCommandLine(JewelryAPIService)
    else:
        print('Unknown action: ' + action)
        sys.exit(1)