@echo off
setlocal
cd /d "%~dp0"
if exist ".analysis-venv\Scripts\python.exe" goto deps
where py >nul 2>nul
if errorlevel 1 goto use_python
py -3 -m venv .analysis-venv
if errorlevel 1 goto failed
goto deps
:use_python
python -m venv .analysis-venv
if errorlevel 1 goto failed
:deps
".analysis-venv\Scripts\python.exe" -m pip install -r requirements-monitor.txt
if errorlevel 1 goto failed
".analysis-venv\Scripts\python.exe" -X utf8 -m can_monitor demo
if errorlevel 1 goto failed
".analysis-venv\Scripts\python.exe" -m streamlit run monitor_app.py --server.address 127.0.0.1 --server.port 8503 --browser.gatherUsageStats false
if errorlevel 1 goto failed
exit /b 0
:failed
echo Monitor start failed. Read the error above.
pause
exit /b 1
