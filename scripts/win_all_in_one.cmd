@echo off
setlocal
cd /d %~dp0..
set "PS1=scripts\win_all_in_one.ps1"

REM Prefer PowerShell Core if available
where /Q pwsh.exe
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
  set RC=%ERRORLEVEL%
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
  set RC=%ERRORLEVEL%
)

if NOT "%RC%"=="0" (
  echo.
  echo [Launcher exited with %RC%] See logs\setup.log for details. The window will remain open above.
  pause
)
exit /b %RC%
