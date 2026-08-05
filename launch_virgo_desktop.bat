@echo off
REM Launcher for Virgo Desktop (PyQt6 GUI).
REM Uses the project interpreter that has PyQt6 installed.
setlocal
set "PROJ=C:\Users\paren\OneDrive\Desktop\agent-framework"
set "PY=C:\Python314\python.exe"
if not exist "%PY%" set "PY=python"
cd /d "%PROJ%"
"%PY%" "%PROJ%\virgo_desktop.py" %*
endlocal
