@echo off
rem Waits for the server to load, then opens the kiosk screen full screen.
timeout /t 40 /nobreak >nul
start "" chrome --start-fullscreen "http://localhost:8000/kiosk"
