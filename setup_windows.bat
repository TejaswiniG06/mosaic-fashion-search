@echo off
REM ============================================================
REM  MOSAIC-Fashion - one-time setup for Windows (no Docker needed)
REM  Needs only Python 3.11 - 3.14 (3.12 recommended) installed (python.org)
REM ============================================================
cd /d "%~dp0"
set PYEXE=
for %%V in (3.12 3.13 3.11 3.14) do (
  if not defined PYEXE ( py -%%V -c "import sys" >nul 2>&1 && set PYEXE=py -%%V )
)
if not defined PYEXE ( python -c "import sys; assert (3,11)<=sys.version_info[:2]<=(3,14)" >nul 2>&1 && set PYEXE=python )
if not defined PYEXE (
  echo [!!] Python 3.11-3.14 not found. Install it from https://www.python.org/downloads/ ^(tick "Add to PATH"^) and run this again.
  pause & exit /b 1
)
echo Using %PYEXE%
if not exist .venv\Scripts\python.exe (
  echo [1/3] creating virtual environment ...
  %PYEXE% -m venv .venv || (echo [!!] venv creation failed & pause & exit /b 1)
)
echo [2/3] installing Python packages (a few minutes) ...
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt -q || (echo [!!] pip install failed & pause & exit /b 1)
echo [3/3] downloading models + portable Qdrant/Redis, writing .env ...
.venv\Scripts\python.exe scripts\launcher.py setup || (echo [!!] setup failed & pause & exit /b 1)
echo.
echo Setup finished. Now run:  start_windows.bat
pause
