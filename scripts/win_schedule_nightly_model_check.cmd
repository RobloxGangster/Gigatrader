@echo off
setlocal
set "TASK_NAME=GigatraderNightlyModelCheck"
set "ROOT=%~dp0.."
set "RUN_CMD=cmd /c \"cd /d \"%ROOT%\" && python -m cli.nightly_model_check %* >> runtime\nightly.log 2>&1\""

schtasks /Create /TN "%TASK_NAME%" /SC DAILY /ST 02:00 /F /TR "%RUN_CMD%"
if %ERRORLEVEL% EQU 0 (
    echo Scheduled task "%TASK_NAME%" created to run nightly at 02:00.
) else (
    echo Failed to create scheduled task "%TASK_NAME%". Error level: %ERRORLEVEL%
)
endlocal
