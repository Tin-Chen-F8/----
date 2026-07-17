@echo off
echo ============================================
echo   Killing all previous services...
echo ============================================
taskkill /f /im python.exe 2>nul
timeout /t 2 /nobreak >nul

echo.
echo ============================================
echo   Cleaning Python cache...
echo ============================================
if exist "%~dp0backend\__pycache__" rd /s /q "%~dp0backend\__pycache__"
if exist "%~dp0virtual_server\__pycache__" rd /s /q "%~dp0virtual_server\__pycache__"

echo.
echo ============================================
echo   Starting all services...
echo ============================================

echo [1/3] Virtual Server (port 9001)...
start "VirtualServer-9001" cmd /k "cd /d %~dp0服务器对接 && python server.py"

echo [2/3] Backend (port 9002)...
start "Backend-9002" cmd /k "cd /d %~dp0backend && python server.py"

timeout /t 5 /nobreak >nul

echo [3/3] Frontend (port 8080)...
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
