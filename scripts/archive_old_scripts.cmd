@echo on
setlocal
set "ROOT=%~dp0"
set "SCRIPTS=%ROOT%"
set "LEGACY=%SCRIPTS%_legacy"
if not exist "%LEGACY%" mkdir "%LEGACY%"

for %%F in ("%SCRIPTS%*.bat" "%SCRIPTS%*.cmd") do (
  if /I not "%%~nxF"=="win_setup_and_run.cmd" if /I not "%%~nxF"=="win_start_api.cmd" if /I not "%%~nxF"=="win_start_ui.cmd" if /I not "%%~nxF"=="archive_old_scripts.cmd" (
    echo Moving "%%~nxF" -> "%LEGACY%"
    move /Y "%%~fF" "%LEGACY%" >NUL
  )
)
echo Done. Archived legacy scripts to "%LEGACY%".
pause
