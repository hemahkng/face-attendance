@echo off
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
del "%STARTUP%\FaceAttendanceServer.bat" 2>nul
del "%STARTUP%\FaceAttendanceKiosk.bat" 2>nul
echo Automatic start removed.
pause
