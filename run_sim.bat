@echo off
cd /d "%~dp0"
echo ============================================
echo   Starting Virtual Server (port 9001)...
echo ============================================
cd /d "%~dp0服务器对接"
python server.py
pause
