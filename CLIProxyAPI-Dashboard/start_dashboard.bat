@echo off
setlocal
cd /d "%~dp0"

set "OPEN_ARG="
if /I "%~1"=="/open" set "OPEN_ARG=-OpenBrowser"

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dashboard.ps1" %OPEN_ARG%
endlocal
