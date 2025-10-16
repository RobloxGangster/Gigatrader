@echo off
cd /d %~dp0
where /Q pwsh.exe
if %ERRORLEVEL%==0 (
  pwsh -NoProfile -ExecutionPolicy Bypass -File "last_test_summary.ps1"
) else (
  powershell -NoProfile -ExecutionPolicy Bypass -File "last_test_summary.ps1"
)
