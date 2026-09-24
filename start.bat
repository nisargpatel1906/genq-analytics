@echo off
cd /d "%~dp0"
echo ========================================
echo        Starting GenQ Analytics
echo ========================================
echo.

echo [1/2] Starting Backend Server (FastAPI on Port 8001 with Realtime Logs)...
start "GenQ Backend (Logs)" cmd /k "cd /d "%~dp0backend" && call .\venv\Scripts\activate.bat && set PYTHONUNBUFFERED=1 && python -m uvicorn main:app --reload --port 8001 --log-level info"

echo [2/2] Starting Frontend Server (Vite on Port 5173)...
start "GenQ Frontend" cmd /k "cd /d "%~dp0frontend" && npm run dev"

echo.
echo ========================================
echo Both servers have been launched in separate windows!
echo.
echo Frontend URL: http://localhost:5173
echo Backend URL:  http://localhost:8001
echo ========================================
pause

