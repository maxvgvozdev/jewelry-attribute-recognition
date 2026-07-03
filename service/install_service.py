import sys
import pathlib
import subprocess
import os
import win32serviceutil

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
PYTHONPATH = f"{REPO_ROOT};{os.environ.get('PYTHONPATH', '')}".strip(";")
sys.path.insert(0, str(REPO_ROOT))

from service.api import SERVICE_NAME


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
        run([sys.executable, '-c', 'import sys,os; print(sys.path); import service.api'])
        run([sys.executable, '-m', 'win32serviceutil', 'InstallService', SERVICE_NAME])
    elif action in ('start', 'stop', 'remove'):
        run([sys.executable, '-m', 'win32serviceutil', action, SERVICE_NAME])
    else:
        print('Unknown action: ' + action)
        sys.exit(1)
