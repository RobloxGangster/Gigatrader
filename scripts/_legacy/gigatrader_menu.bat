@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Gigatrader - One Click Menu

rem ---------- Resolve repo root ----------
set REPO_ROOT=%~dp0..
for %%I in ("%REPO_ROOT%") do set REPO_ROOT=%%~fI

rem ---------- Functions ----------
:ensure_python
  set "PY="
  for /f "tokens=*" %%V in ('py -3.11 -V 2^>NUL') do set "PY=py -3.11"
  if "%PY%"=="" (
    for /f "tokens=2 delims= " %%v in ('python -V 2^>NUL') do (
      echo %%v | findstr /r "^3\.11\." >NUL
      if not errorlevel 1 set "PY=python"
    )
  )
  if "%PY%"=="" (
    echo [!] Python 3.11 not found. Install: https://www.python.org/downloads/windows/
    pause & exit /b 1
  )
  goto :eof

:ensure_venv
  if not exist "%REPO_ROOT%\.venv\Scripts\python.exe" (
    echo [+] Creating virtual environment ...
    %PY% -m venv "%REPO_ROOT%\.venv" || (echo [!] venv failed & pause & exit /b 1)
  )
  goto :eof

:activate_venv
  call "%REPO_ROOT%\.venv\Scripts\activate.bat" || (echo [!] activate failed & pause & exit /b 1)
  goto :eof

:install_update
  call :ensure_python
  call :ensure_venv
  call :activate_venv

  if not exist "%REPO_ROOT%\requirements.txt" (
    echo [-] Creating minimal requirements.txt
    > "%REPO_ROOT%\requirements.txt" echo typer>=0.12
    >> "%REPO_ROOT%\requirements.txt" echo pydantic>=2
    >> "%REPO_ROOT%\requirements.txt" echo python-dotenv>=1
    >> "%REPO_ROOT%\requirements.txt" echo rich>=13
    >> "%REPO_ROOT%\requirements.txt" echo alpaca-py>=0.30
  )

  echo [+] Upgrading pip/setuptools/wheel...
  python -m pip install -U pip setuptools wheel || (echo [!] pip upgrade failed & pause & exit /b 1)

  echo [+] Installing requirements...
  python -m pip install -r "%REPO_ROOT%\requirements.txt" || (echo [!] deps failed & pause & exit /b 1)

  if exist "%REPO_ROOT%\pyproject.toml" (
    echo [+] Installing package (editable)...
    python -m pip install -e "%REPO_ROOT%" || (echo [!] editable install failed & pause & exit /b 1)
  )

  if not exist "%REPO_ROOT%\.env" (
    if exist "%REPO_ROOT%\.env.example" (
      copy /Y "%REPO_ROOT%\.env.example" "%REPO_ROOT%\.env" >NUL
      echo [-] Created .env from .env.example
    ) else (
      > "%REPO_ROOT%\.env" (
        echo ALPACA_API_KEY=
        echo ALPACA_API_SECRET=
        echo ALPACA_BASE_URL=https://paper-api.alpaca.markets
        echo PROFILE=paper
        echo LIVE_TRADING=
        echo ALPACA_DATA_FEED=SIP
        echo DATA_STALENESS_SEC=5
        echo STRICT_SIP=
      )
      echo [-] Created minimal .env
    )
  )

  if not exist "%REPO_ROOT%\config.yaml" (
    if exist "%REPO_ROOT%\config.example.yaml" (
      copy /Y "%REPO_ROOT%\config.example.yaml" "%REPO_ROOT%\config.yaml" >NUL
      echo [-] Created config.yaml from config.example.yaml
    ) else (
      > "%REPO_ROOT%\config.yaml" (
        echo profile: paper
        echo universe: [AAPL, MSFT]
        echo timeframe: "1Min"
        echo risk:
        echo ^  daily_loss_limit_pct: 3
        echo ^  max_positions: 5
        echo execution:
        echo ^  tif: day
      )
      echo [-] Created minimal config.yaml
    )
  )

  echo [+] Install/Update complete.
  goto :menu

:launch_new_window
  rem %1 = window title, %2 = command string to run inside venv
  if not exist "%REPO_ROOT%\.venv\Scripts\activate.bat" (
    echo [!] venv missing. Run option 1 (Install/Update) first.
    pause & goto :menu
  )
  start "%~1" cmd /k "cd /d \"%REPO_ROOT%\" ^&^& call .venv\Scripts\activate.bat ^&^& %~2"
  goto :eof

:run_paper
  set "PROFILE=paper"
  set "LIVE_TRADING="
  set "CFG=%REPO_ROOT%\config.yaml"
  call :launch_new_window "Gigatrader Paper" "(where trade >NUL 2^>^&1 ^&^& trade paper --config \"%CFG%\" ^|^| python -m app.cli paper --config \"%CFG%\")"
  goto :menu

:run_backtest
  set /p DAYS=Enter lookback days (default 5): 
  if "%DAYS%"=="" set DAYS=5
  set /p UNI=Enter universe symbols comma-separated (default AAPL,MSFT): 
  if "%UNI%"=="" set UNI=AAPL,MSFT
  set "CFG=%REPO_ROOT%\config.yaml"
  call :launch_new_window "Gigatrader Backtest" "(where trade >NUL 2^>^&1 ^&^& trade backtest --config \"%CFG%\" --days %DAYS% --universe %UNI% ^|^| python -m app.cli backtest --config \"%CFG%\" --days %DAYS% --universe %UNI%)"
  goto :menu

:verify_feed
  call :launch_new_window "Gigatrader Verify Feed" "(where trade >NUL 2^>^&1 ^&^& trade verify-feed ^|^| python -m app.cli verify-feed)"
  goto :menu

:place_test_order
  set /p OTYPE=Order type [market|limit] (default market): 
  if "%OTYPE%"=="" set OTYPE=market
  set /p SYM=Symbol (default AAPL): 
  if "%SYM%"=="" set SYM=AAPL
  set /p QTY=Quantity (default 1): 
  if "%QTY%"=="" set QTY=1
  set LMT=
  if /I "%OTYPE%"=="limit" (
    set /p LMT=Limit price (required for limit): 
    if "%LMT%"=="" (
      echo [!] Limit price is required for limit orders.
      pause & goto :menu
    )
    call :launch_new_window "Gigatrader Test Order" "(where trade >NUL 2^>^&1 ^&^& trade place-test-order --type limit --symbol %SYM% --qty %QTY% --limit-price %LMT% ^|^| python -m app.cli place-test-order --type limit --symbol %SYM% --qty %QTY% --limit-price %LMT%)"
  ) else (
    call :launch_new_window "Gigatrader Test Order" "(where trade >NUL 2^>^&1 ^&^& trade place-test-order --type market --symbol %SYM% --qty %QTY% ^|^| python -m app.cli place-test-order --type market --symbol %SYM% --qty %QTY%)"
  )
  goto :menu

:stream_latency
  set /p SYM=Symbols comma-separated (default AAPL,MSFT): 
  if "%SYM%"=="" set SYM=AAPL,MSFT
  set /p SEC=Seconds to sample (default 30): 
  if "%SEC%"=="" set SEC=30
  call :launch_new_window "Gigatrader Feed Latency" "(where trade >NUL 2^>^&1 ^&^& trade feed-latency --symbols %SYM% --seconds %SEC% ^|^| python -m app.cli feed-latency --symbols %SYM% --seconds %SEC%)"
  goto :menu

rem ---------- Menu ----------
:menu
  cls
  echo ===========================================
  echo   Gigatrader - One Click Menu
  echo   Repo: %REPO_ROOT%
  echo ===========================================
  echo   1) Install / Update
  echo   2) Run PAPER (new window)
  echo   3) Run BACKTEST (new window)
  echo   4) Verify FEED (SIP/IEX)
  echo   5) Place TEST ORDER (paper only)
  echo   6) Stream & LATENCY (new window)
  echo   0) Exit
  echo -------------------------------------------
  set /p CH=Choose an option: 
  if "%CH%"=="1" goto :install_update
  if "%CH%"=="2" goto :run_paper
  if "%CH%"=="3" goto :run_backtest
  if "%CH%"=="4" goto :verify_feed
  if "%CH%"=="5" goto :place_test_order
  if "%CH%"=="6" goto :stream_latency
  if "%CH%"=="0" exit /b 0
  goto :menu
