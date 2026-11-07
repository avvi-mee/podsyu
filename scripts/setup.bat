@echo off
REM One-time installer: Python venv + packages, frontend build, face model, Ollama model.
setlocal EnableExtensions
cd /d "%~dp0.."
echo.
echo === Podcast Shorts Factory setup ===
echo.

where ffmpeg >nul 2>nul || (
  echo [ERROR] FFmpeg not found. Install it with:  winget install Gyan.FFmpeg
  echo         then open a NEW terminal and run setup again.
  exit /b 1
)
where node >nul 2>nul || (
  echo [ERROR] Node.js not found. Install the LTS version from https://nodejs.org
  exit /b 1
)

REM Prefer Python 3.13 / 3.12 / 3.11 (CTranslate2 + OpenCV wheels exist for these)
set "PY="
for %%V in (3.13 3.12 3.11) do (
  if not defined PY ( py -%%V -c "import sys" >nul 2>nul && set "PY=py -%%V" )
)
if not defined PY ( where python >nul 2>nul && set "PY=python" )
if not defined PY (
  echo [ERROR] Python 3.11-3.13 not found. Install Python 3.13 from https://www.python.org/downloads/
  exit /b 1
)

if not exist backend\.venv\Scripts\python.exe (
  echo [1/5] Creating Python virtual environment with %PY% ...
  %PY% -m venv backend\.venv || exit /b 1
)
echo [2/5] Installing Python packages (first run downloads ~1.5 GB incl. CUDA libraries) ...
backend\.venv\Scripts\python.exe -m pip install --upgrade pip >nul
backend\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt || (
  echo [ERROR] pip install failed. Check your internet connection and retry.
  exit /b 1
)

echo [3/5] Installing and building the dashboard ...
pushd frontend
call npm install --no-audit --no-fund || (popd & echo [ERROR] npm install failed & exit /b 1)
call npm run build || (popd & echo [ERROR] Frontend build failed & exit /b 1)
popd

echo [4/5] Downloading models (local voice ~350 MB, face detector) ...
backend\.venv\Scripts\python.exe scripts\download_models.py || echo [WARN] Some models failed to download - re-run scripts\download_models.py later.

echo [5/5] Checking Ollama ...
where ollama >nul 2>nul || (
  echo [WARN] Ollama not installed. Install from https://ollama.com/download then run:  ollama pull qwen2.5:7b-instruct
  goto :done
)
ollama list | findstr /C:"qwen2.5" >nul || (
  echo Pulling qwen2.5:7b-instruct ^(4.7 GB^) ...
  ollama pull qwen2.5:7b-instruct
)

:done
if not exist .env copy .env.example .env >nul
echo.
echo Setup complete. Run start.bat to launch the dashboard.
exit /b 0
