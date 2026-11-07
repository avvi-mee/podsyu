@echo off
REM Stop Podcast Shorts Factory. Jobs and uploads in progress resume automatically on next start.
setlocal
set "PSF_ROOT=%~dp0"
echo Stopping backend gracefully ...
curl.exe -s -m 5 -X POST http://127.0.0.1:8000/api/system/shutdown >nul 2>nul
ping -n 4 127.0.0.1 >nul
REM Only stop python/node processes started from THIS folder - never other apps using the same ports.
powershell -NoProfile -Command "$root = $env:PSF_ROOT.TrimEnd('\'); Get-CimInstance Win32_Process -Filter \"Name='python.exe' or Name='node.exe'\" | Where-Object { $_.CommandLine -and $_.CommandLine.Contains($root) } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue; Write-Host ('Stopped ' + $_.Name + ' (pid ' + $_.ProcessId + ')') }"
echo Done.
