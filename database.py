import sqlite3
from contextlib import contextmanager
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "attendance.db"

DEFAULT_SETTINGS = {
    "company_name": "My Company",
    "office_start": "09:30",
    "grace_minutes": "10",
    "threshold": "0.45",
    "min_gap_minutes": "10",
    "weekly_off": "Sunday",
    "liveness": "1",
    "backup_folder": "",
}


@contextmanager
def db():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init_db():
    with db() as con:
        con.execute("""CREATE TABLE IF NOT EXISTS employees (
            emp_id TEXT PRIMARY KEY, name TEXT NOT NULL, embedding BLOB NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
        cols = {r["name"] for r in con.execute("PRAGMA table_info(employees)")}
        if "department" not in cols:
            con.execute("ALTER TABLE employees ADD COLUMN department TEXT DEFAULT ''")
        if "active" not in cols:
            con.execute("ALTER TABLE employees ADD COLUMN active INTEGER DEFAULT 1")
        con.execute("""CREATE TABLE IF NOT EXISTS attendance (
            id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT NOT NULL, name TEXT NOT NULL,
            timestamp TEXT NOT NULL, date TEXT NOT NULL, event TEXT NOT NULL)""")
        acols = {r["name"] for r in con.execute("PRAGMA table_info(attendance)")}
        for col, ddl in (("source", "TEXT DEFAULT 'kiosk'"), ("note", "TEXT DEFAULT ''"),
                         ("voided", "INTEGER DEFAULT 0")):
            if col not in acols:
                con.execute(f"ALTER TABLE attendance ADD COLUMN {col} {ddl}")
        con.execute("CREATE INDEX IF NOT EXISTS idx_att ON attendance(date, emp_id)")
        con.execute("""CREATE TABLE IF NOT EXISTS leaves (
            id INTEGER PRIMARY KEY AUTOINCREMENT, emp_id TEXT NOT NULL, day TEXT NOT NULL,
            type TEXT NOT NULL, note TEXT DEFAULT '', UNIQUE (emp_id, day))""")
        con.execute("CREATE TABLE IF NOT EXISTS holidays (day TEXT PRIMARY KEY, name TEXT NOT NULL)")
        con.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT)")
        for k, v in DEFAULT_SETTINGS.items():
            con.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))


def get_settings(con):
    s = dict(DEFAULT_SETTINGS)
    s.update({r["key"]: r["value"] for r in con.execute("SELECT key, value FROM settings")})
    return s


def set_setting(con, key, value):
    con.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (key, str(value)))
