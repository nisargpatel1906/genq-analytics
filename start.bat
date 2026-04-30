@echo off
echo ========================================
echo        Starting GenQ Analytics
echo ========================================
echo.

echo [1/2] Starting Backend Server (FastAPI)...
start "GenQ Backend" cmd /k "cd backend && call .\venv\Scripts\activate.bat && python -m uvicorn main:app --reload --port 8000"

echo [2/2] Starting Frontend Server (Vite)...
start "GenQ Frontend" cmd /k "cd frontend && npm run dev"

echo.
echo ========================================
echo Both servers have been launched in separate windows!
echo.
echo Frontend URL: http://localhost:5173
echo Backend URL:  http://localhost:8000
echo ========================================
pause
