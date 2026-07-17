@echo off
echo ============================================
echo   Coating Workshop Monitor - Starting...
echo ============================================

echo [1/3] Starting Virtual Server (port 9001)...
start "VirtualServer-9001" cmd /k "cd /d %~dp0服务器对接 && python server.py"

echo [2/3] Starting Backend (port 9002)...
start "Backend-9002" cmd /k "cd /d %~dp0backend && python server.py"

timeout /t 5 /nobreak >nul

echo [3/3] Starting Frontend (port 8080)...
start "Frontend-8080" cmd /k "cd /d %~dp0frontend && python -m http.server 8080"

echo.
echo ============================================
echo   All services started!
echo   Frontend : http://127.0.0.1:8080
echo   Backend  : http://127.0.0.1:9002
echo   Virtual  : http://127.0.0.1:9001
echo ============================================
echo.
echo Press any key to close this window (services keep running)
pause >nul
