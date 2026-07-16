@echo off
setlocal enabledelayedexpansion

:: Add virgo's Python Scripts directory to PATH for this session
for /f "tokens=*" %%i in ('where python') do set PYTHON_DIR=%%~dpi
if defined PYTHON_DIR (
    set "SCRIPTS_DIR=%PYTHON_DIR%..\Scripts"
    if exist "!SCRIPTS_DIR!" (
        set "PATH=!SCRIPTS_DIR!;!PATH!"
    )
)

:: If no arguments, launch the TUI dashboard
if "%~1"=="" (
    python "%~dp0virgo_menu.py"
    exit /b !ERRORLEVEL!
)

:: Otherwise pass through to cli.py
python "%~dp0cli.py" %*
exit /b %ERRORLEVEL%
