@echo off
cd /d %~dp0..
set "PS1=scripts\test_all.ps1"
where /Q pwsh.exe
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
)
echo.
pause
