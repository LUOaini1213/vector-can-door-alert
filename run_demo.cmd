@echo off
setlocal
cd /d "%~dp0"
python -c "import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)" >nul 2>&1
if errorlevel 1 (
  echo Python 3.10 or newer is required. Open README.md for instructions.
  pause
  exit /b 2
)
python -X utf8 -m door_alert demo --output reports\demo
if errorlevel 1 (
  echo Simulation failed. See the error above and the generated report.
  pause
  exit /b 1
)
start "" "reports\demo\report.html"
echo Done. Report is saved in reports\demo.
pause
