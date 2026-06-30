@echo off
setlocal

:: Install dependencies
echo Installing Python dependencies...
pip install -r requirements.txt

echo.
echo Installing Windows service...
python install_service.py install

echo.
echo Starting service...
python install_service.py start

echo.
echo Done. Service should be running on %API_HOST%:%API_PORT%
pause
