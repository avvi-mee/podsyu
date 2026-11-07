@echo off
REM Launch Podcast Shorts Factory: backend (127.0.0.1:8000) + dashboard (http://localhost:3000)
REM Dashboard port: set PSF_FRONTEND_PORT in .env (or the environment) if 3000 is taken by another app.
setlocal EnableExtensions
cd /d "%~dp0"
title Shorts Factory launcher
if not defined PSF_FRONTEND_PORT if exist .env for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do if /i "%%a"=="PSF_FRONTEND_PORT" set "PSF_FRONTEND_PORT=%%b"
if not defined PSF_FRONTEND_PORT set "PSF_FRONTEND_PORT=3000"
set "PORT=%PSF_FRONTEND_PORT%"

where ffmpeg >nul 2>nul || ( echo [ERROR] FFmpeg is not on PATH. Run:  winget install Gyan.FFmpeg  then reopen this window. & goto :fail )
where node >nul 2>nul || ( echo [ERROR] Node.js is not installed. Get the LTS version from https://nodejs.org & goto :fail )

if not exist backend\.venv\Scripts\python.exe (
  echo First run detected - running setup ...
  call scripts\setup.bat || goto :fail
)
if not exist frontend\node_modules (
  pushd frontend & call npm install --no-audit --no-fund & popd
)
if not exist frontend\.next\BUILD_ID (
  echo Building dashboard ...
  pushd frontend & call npm run build & popd
  if not exist frontend\.next\BUILD_ID ( echo [ERROR] Dashboard build failed. & goto :fail )
)

REM Exit code bits: 1 = backend (8000) already ours, 2 = dashboard already ours; 9 = a port is used by another program
set "PSF_ROOT=%~dp0"
powershell -NoProfile -Command "$root=$env:PSF_ROOT.TrimEnd('\'); $code=0; $bit=1; foreach($port in 8000,$env:PORT){ foreach($c in @(Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)){ $cmd=(Get-CimInstance Win32_Process -Filter ('ProcessId=' + $c.OwningProcess)).CommandLine; if($cmd -and $cmd.Contains($root)){ $code=$code -bor $bit } else { Write-Host ('[ERROR] Port ' + $port + ' is used by another program: ' + $cmd); exit 9 } }; $bit=2 }; exit $code"
set "RUNNING=%errorlevel%"
if "%RUNNING%"=="9" (
  echo Stop that program, or run the dashboard on another port: add  PSF_FRONTEND_PORT=3001  to .env
  goto :fail
)
if "%RUNNING%"=="3" (
  echo The app is already running. Opening the dashboard ...
  start "" http://localhost:%PORT%
  exit /b 0
)

REM Ollama (local LLM) - start it if installed but not running
curl.exe -s -m 2 http://127.0.0.1:11434/api/version >nul 2>nul
if errorlevel 1 (
  where ollama >nul 2>nul && ( echo Starting Ollama ... & start "Ollama" /min ollama serve ) || echo [WARN] Ollama not installed - AI clip detection will fail until you install it. See README.
)

if not "%RUNNING%"=="1" (
  echo Starting backend ...
  start "Shorts Factory - Backend" /min /D "%~dp0backend" ".venv\Scripts\python.exe" run.py
)
if not "%RUNNING%"=="2" (
  echo Starting dashboard ...
  start "Shorts Factory - Dashboard" /min /D "%~dp0frontend" cmd /c npm run start -- -H 127.0.0.1 -p %PORT%
)

echo Waiting for services ...
powershell -NoProfile -Command "for($i=0;$i -lt 90;$i++){ try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:8000/api/settings -TimeoutSec 2 | Out-Null; exit 0 } catch { Start-Sleep 1 } }; exit 1"
if errorlevel 1 ( echo [ERROR] Backend did not start. Open the "Shorts Factory - Backend" window or data\logs\app.log for details. & goto :fail )
powershell -NoProfile -Command "for($i=0;$i -lt 60;$i++){ try { Invoke-WebRequest -UseBasicParsing http://127.0.0.1:%PORT% -TimeoutSec 3 | Out-Null; exit 0 } catch { Start-Sleep 1 } }; exit 1"
if errorlevel 1 ( echo [ERROR] Dashboard did not start. Check the "Shorts Factory - Dashboard" window. & goto :fail )

start "" http://localhost:%PORT%
echo.
echo Running at http://localhost:%PORT%   (run stop.bat to stop)
echo Keep this PC on and the app running for app-managed scheduled uploads.
ping -n 6 127.0.0.1 >nul
exit /b 0

:fail
echo.
REM the Start-menu shortcut runs this window minimized, so say so on screen
powershell -NoProfile -Command "(New-Object -ComObject WScript.Shell).Popup('Shorts Clipper could not start. The launcher window on the taskbar shows why.',0,'Shorts Clipper',16)" >nul
pause
exit /b 1
