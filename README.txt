FACE ATTENDANCE
===============

RUN IT
  1. cd /d D:\Hemanth\Projects\face-attendance1
  2. venv\Scripts\activate
  3. python -m uvicorn app:app --host 127.0.0.1 --port 8000
  Kiosk:  http://localhost:8000/kiosk      Admin:  http://localhost:8000/admin
  (Use "localhost" exactly: browsers only allow the camera there.)
  Only ONE server may run at a time. Stop it with Ctrl+C before starting it again.

START AUTOMATICALLY WHEN THE PC TURNS ON
  Double-click install_autostart.bat, answer y/n for the full-screen kiosk, then sign out and in.
  The server runs in a minimised window (do not close it). Its log is logs\server.log.
  Undo with remove_autostart.bat.
  For a PC that should start by itself with nobody typing a password, set Windows to sign in
  automatically (that is a Windows setting, not part of this app).

HOLIDAYS
  Settings > Holidays: add public holidays so nobody is counted absent on those dates.
  (Weekly off days are set in Settings too.)

LEAVE
  Corrections > Mark leave: pick an employee and dates. Leave days are not counted absent.
  If the person comes in anyway, they are still recorded as present.

BACKUPS
  The server makes one backup a day, and keeps the last 30 in the "backups" folder.
  Settings > Extra backup folder also copies each one to a USB drive or OneDrive folder.
  Settings > Back up now makes one immediately.
  Backups contain face data. Keep them somewhere only trusted people can open.

RESTORE A BACKUP
  1. Stop the server (Ctrl+C).
  2. Copy attendance.db to a safe place, in case you need it again.
  3. Copy the backup you want (backups\attendance_YYYY-MM-DD_HHMMSS.db) over attendance.db
     in the project folder.
  4. Start the server again.

IF SOMETHING GOES WRONG
  "port 8000 in use":   netstat -ano | findstr :8000   then   taskkill /PID <number> /F
  Forgot admin password: stop the server, run python reset_password.py, start the server,
                         sign in with admin123 and change it.
