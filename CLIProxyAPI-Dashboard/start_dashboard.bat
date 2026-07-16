@echo off
setlocal
cd /d "%~dp0"

set "OPEN_ARG="
if /I "%~1"=="/open" set "OPEN_ARG=-OpenBrowser"

echo.
echo [CLIProxyAPI Dashboard] starting...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start_dashboard.ps1" %OPEN_ARG%
set "ERR=%ERRORLEVEL%"

if not "%ERR%"=="0" (
  echo.
  echo [CLIProxyAPI Dashboard] start failed. code=%ERR%
  echo Window will stay open so you can read the error.
  echo.
  pause
  endlocal & exit /b %ERR%
)

echo.
echo [CLIProxyAPI Dashboard] start OK
echo Open: http://127.0.0.1:8765
echo.
rem Keep the console visible briefly so double-click launches are not silent.
timeout /t 3 /nobreak >nul
endlocal & exit /b 0
