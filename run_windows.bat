@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if errorlevel 1 (
  echo Python launcher ^(py^) was not found. Install Python 3.11-3.13 from python.org.
  pause
  exit /b 1
)
set "PYVER=-3"
py -3.12 -c "import sys" >nul 2>nul
if not errorlevel 1 set "PYVER=-3.12"
if "%PYVER%"=="-3" (
  py -3.11 -c "import sys" >nul 2>nul
  if not errorlevel 1 set "PYVER=-3.11"
)
if not exist ".venv_windows\Scripts\python.exe" (
  echo Creating Windows Python environment...
  py %PYVER% -m venv .venv_windows
  if errorlevel 1 (pause & exit /b 1)
)
echo Installing dependencies...
".venv_windows\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 (pause & exit /b 1)
echo Starting eBay Research AI. Open http://localhost:8501 if the browser does not appear.
".venv_windows\Scripts\python.exe" -m streamlit run app.py --server.address localhost
pause
