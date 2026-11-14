@echo off
title Zoom War
cd /d "%~dp0"

rem "python --version", not "where": the Microsoft Store alias also passes "where" but is not Python
python --version >nul 2>nul || (
    echo Python was not found. Install Python from python.org and tick "Add to PATH".
    pause
    exit /b
)

rem Windows Terminal ignores an app's icon: reopen in the classic console so the
rem Zoom War icon shows in the title bar and on the taskbar.
if not "%~1"=="--console" (
    python -c "import ctypes as c,sys;b=c.create_unicode_buffer(64);c.windll.user32.GetClassNameW(c.windll.kernel32.GetConsoleWindow(),b,64);sys.exit(b.value!='ConsoleWindowClass')" || (
        start "" conhost.exe cmd /c call "%~f0" --console
        exit /b
    )
)

rem Install pywinauto once (for clicking mic, camera and Join automatically)
python -c "import pywinauto" 2>nul || python -m pip install pywinauto

python zoom_war.py
