@echo off
rem Starts the attendance server and restarts it if it ever stops unexpectedly.
cd /d "%~dp0"
if not exist logs mkdir logs
title Face Attendance Server - keep this window open (minimise it)
:loop
echo [%date% %time%] server starting >> logs\server.log
call venv\Scripts\activate
python -m uvicorn app:app --host 127.0.0.1 --port 8000 --no-access-log >> logs\server.log 2>&1
echo [%date% %time%] server stopped, restarting in 5 seconds >> logs\server.log
timeout /t 5 /nobreak >nul
goto loop
