import sqlite3
from pathlib import Path
import database as dbm

db_path = dbm.DB_PATH.as_posix()

con = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
con.row_factory = sqlite3.Row

try:
    print("\n--- EMPLOYEE ---")
    rows = con.execute("""
        SELECT emp_id, name, created_at, active
        FROM employees
        WHERE emp_id = 'E001'
    """).fetchall()

    for r in rows:
        print(dict(r))

    print("\n--- LEAVE RECORDS ---")
    rows = con.execute("""
        SELECT emp_id, day, type, note
        FROM leaves
        WHERE emp_id = 'E001'
          AND day BETWEEN '2026-11-17' AND '2026-11-18'
        ORDER BY day
    """).fetchall()

    for r in rows:
        print(dict(r))

    print("\n--- ATTENDANCE ON NOV 17 ---")
    rows = con.execute("""
        SELECT timestamp, event, source, note, voided
        FROM attendance
        WHERE emp_id = 'E001'
          AND date = '2026-11-17'
        ORDER BY timestamp
    """).fetchall()

    for r in rows:
        print(dict(r))

    print("\n--- HOLIDAY CHECK ---")
    rows = con.execute("""
        SELECT day, name
        FROM holidays
        WHERE day BETWEEN '2026-11-17' AND '2026-11-18'
    """).fetchall()

    for r in rows:
        print(dict(r))

    print("\n--- SETTINGS ---")
    rows = con.execute("""
        SELECT key, value
        FROM settings
        WHERE key IN ('weekly_off', 'office_start', 'grace_minutes')
    """).fetchall()

    for r in rows:
        print(dict(r))

finally:
    con.close()
