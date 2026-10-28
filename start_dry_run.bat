@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title sensors-arm dry-run :6018
call "%~dp0..\scripts\env_python.bat" || goto :fail

echo [sensors-arm] dry-run  http://127.0.0.1:6018/
sensors-arm run -c configs/default.yaml --dry-run --port 6018
set "ERR=%ERRORLEVEL%"
goto :end

:fail
set "ERR=1"
:end
echo.
echo Exit code %ERR%. Press any key to close.
pause >nul
exit /b %ERR%
