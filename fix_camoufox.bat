@echo off
setlocal EnableExtensions EnableDelayedExpansion
title Camoufox Quick Fix - reinstall + fetch
color 0A

echo ============================================================
echo   CAMOUFOX QUICK FIX
echo   - clears broken npm/camoufox caches
echo   - reinstalls camoufox (Node + Python)
echo   - downloads the browser (camoufox fetch)
echo   - verifies version.json
echo ============================================================
echo.

REM ------------------------------------------------------------
REM 0) Locate Python (try py launcher, then python)
REM ------------------------------------------------------------
set "PY="
where py >nul 2>nul && set "PY=py -3"
if not defined PY (
    where python >nul 2>nul && set "PY=python"
)
if defined PY (
    echo [OK] Python found: %PY%
    %PY% --version
) else (
    echo [!] No Python found - will use the Node.js path only.
)
echo.

REM ------------------------------------------------------------
REM 1) Locate the tool folder that contains camoufox-js
REM    (override with:  fix_camoufox.bat "D:\path\to\GOLOGIN_TOOL")
REM ------------------------------------------------------------
set "TOOLDIR=%~1"
if not defined TOOLDIR (
    for %%D in (
        "%USERPROFILE%\OneDrive\Desktop\GOLOGIN_TOOL_FIREFOX\GOLOGIN_TOOL_FIREFOX\GOLOGIN_TOOL"
        "%USERPROFILE%\Desktop\GOLOGIN_TOOL_FIREFOX\GOLOGIN_TOOL_FIREFOX\GOLOGIN_TOOL"
        "%USERPROFILE%\OneDrive\Desktop\GOLOGIN_TOOL_FIREFOX"
        "%USERPROFILE%\Desktop\GOLOGIN_TOOL_FIREFOX"
    ) do (
        if not defined TOOLDIR if exist "%%~fD\node_modules\camoufox-js" set "TOOLDIR=%%~fD"
    )
)
if defined TOOLDIR (
    echo [OK] Tool folder: %TOOLDIR%
) else (
    echo [!] Tool folder with node_modules\camoufox-js not found.
    echo     ^(Pass it as an argument to use the local copy: fix_camoufox.bat "C:\path\to\GOLOGIN_TOOL"^)
)
echo.

REM ------------------------------------------------------------
REM 2) Clean broken caches
REM ------------------------------------------------------------
echo [1/6] Cleaning npm cache...
call npm cache clean --force >nul 2>nul
if errorlevel 1 (
    echo     npm cache clean failed or npm missing - continuing...
) else (
    echo     npm cache cleaned.
)

echo [2/6] Removing broken camoufox cache (version.json / partial download)...
set "FOXCACHE=%LOCALAPPDATA%\camoufox"
if exist "%FOXCACHE%" (
    rmdir /s /q "%FOXCACHE%" 2>nul
    if exist "%FOXCACHE%" (
        echo     [!] Could not delete "%FOXCACHE%" - close the tool/browser and rerun this file.
    ) else (
        echo     Removed "%FOXCACHE%".
    )
) else (
    echo     Nothing to remove.
)
echo.

REM ------------------------------------------------------------
REM 3) Reinstall camoufox-js + fetch browser (Node path)
REM ------------------------------------------------------------
echo [3/6] Reinstalling camoufox-js and fetching the browser (Node)...
set "NODE_OK=0"
where npm >nul 2>nul
if errorlevel 1 (
    echo     [!] npm not found - install Node.js LTS: https://nodejs.org/
) else (
    if defined TOOLDIR (
        pushd "%TOOLDIR%"
        call npm install camoufox-js --save
        if not errorlevel 1 set "NODE_OK=1"
        popd
    ) else (
        call npm install -g camoufox-js
        if not errorlevel 1 set "NODE_OK=1"
    )
)
echo.

REM ------------------------------------------------------------
REM 4) Fetch the browser (retry 3x - this is the step that failed)
REM ------------------------------------------------------------
echo [4/6] Downloading the Camoufox browser (can take a few minutes)...
set "FETCH_OK=0"
if "%NODE_OK%"=="1" (
    if defined TOOLDIR (
        pushd "%TOOLDIR%"
        for /L %%I in (1,1,3) do (
            if "!FETCH_OK!"=="0" (
                echo     Attempt %%I of 3: npx camoufox-js fetch
                call npx --no-install camoufox-js fetch
                if not errorlevel 1 set "FETCH_OK=1"
            )
        )
        popd
    ) else (
        for /L %%I in (1,1,3) do (
            if "!FETCH_OK!"=="0" (
                echo     Attempt %%I of 3: npx camoufox-js fetch
                call npx --yes camoufox-js fetch
                if not errorlevel 1 set "FETCH_OK=1"
            )
        )
    )
)
if "%FETCH_OK%"=="0" if defined PY (
    echo     Trying the Python package instead...
    %PY% -m pip install --upgrade camoufox
    for /L %%I in (1,1,3) do (
        if "!FETCH_OK!"=="0" (
            echo     Attempt %%I of 3: python -m camoufox fetch
            %PY% -m camoufox fetch
            if not errorlevel 1 set "FETCH_OK=1"
        )
    )
)
echo.

REM ------------------------------------------------------------
REM 5) Last-resort Python reinstall (if Python path never ran)
REM ------------------------------------------------------------
echo [5/6] Ensuring the Python camoufox package is installed...
if defined PY (
    %PY% -m pip install --upgrade camoufox >nul 2>nul
    where camoufox >nul 2>nul || echo     Note: use "python -m camoufox fetch" if the camoufox command is still missing.
)
echo.

REM ------------------------------------------------------------
REM 6) Verify version.json
REM ------------------------------------------------------------
echo [6/6] Verifying install...
set "VERFILE=%LOCALAPPDATA%\camoufox\camoufox\Cache\version.json"
if exist "%VERFILE%" (
    echo.
    echo ============================================================
    echo   SUCCESS - version.json exists:
    echo   %VERFILE%
    echo   You can now run the tool again.
    echo ============================================================
) else (
    echo.
    echo ============================================================
    echo   STILL MISSING - version.json was not created.
    echo   Most common causes:
    echo     1) network / proxy / firewall blocks the download
    echo        ^(try another network, or disable the proxy/VPN^)
    echo     2) antivirus quarantined the extracted browser
    echo     3) old Node.js - install the latest Node.js LTS
    echo   Then run this file again.
    echo ============================================================
)

echo.
pause
endlocal
