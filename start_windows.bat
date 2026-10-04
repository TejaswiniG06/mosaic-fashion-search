@echo off
REM Start MOSAIC-Fashion (first run also loads and indexes the 5,000-product catalogue)
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe ( echo Run setup_windows.bat first. & pause & exit /b 1 )
.venv\Scripts\python.exe scripts\launcher.py start
pause
