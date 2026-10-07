@echo off
setlocal
powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -File "%~dp0package.ps1" -Action Stop
set "scoutExit=%ERRORLEVEL%"
if not "%scoutExit%"=="0" pause
exit /b %scoutExit%
