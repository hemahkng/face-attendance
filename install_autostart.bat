@echo off
rem Makes the server start automatically when you sign in to Windows.
set "STARTUP=%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup"
set "HERE=%~dp0"

> "%STARTUP%\FaceAttendanceServer.bat" echo @echo off
>> "%STARTUP%\FaceAttendanceServer.bat" echo start "Face Attendance Server" /min cmd /c "%HERE%start_server.bat"
echo Server will now start automatically when you sign in.

set /p KIOSK=Also open the kiosk screen full screen at sign-in? (y/n): 
if /i "%KIOSK%"=="y" (
  > "%STARTUP%\FaceAttendanceKiosk.bat" echo @echo off
  >> "%STARTUP%\FaceAttendanceKiosk.bat" echo start "" /min cmd /c "%HERE%open_kiosk.bat"
  echo Kiosk screen will open automatically too.
)
echo.
echo Done. Sign out and back in (or restart) to test it.
pause
