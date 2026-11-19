import sqlite3

con = sqlite3.connect("attendance.db")
con.execute("DELETE FROM settings WHERE key IN ('admin_password', 'password_is_default')")
con.commit()
print("Password reset. Start the server, then sign in with admin123 and change it in Settings.")
