import sqlite3
from datetime import date
from reports import build_report

today = date.today().isoformat()

con = sqlite3.connect(":memory:")
con.row_factory = sqlite3.Row

# Minimal schema required by reports.py
con.execute("""
CREATE TABLE employees (
    emp_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT,
    active INTEGER,
    created_at TEXT
)
""")

con.execute("""
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id TEXT NOT NULL,
    name TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    date TEXT NOT NULL,
    event TEXT NOT NULL,
    source TEXT DEFAULT 'kiosk',
    voided INTEGER DEFAULT 0
)
""")

con.execute("""
CREATE TABLE holidays (
    day TEXT PRIMARY KEY,
    name TEXT NOT NULL
)
""")

con.execute("""
CREATE TABLE leaves (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    emp_id TEXT NOT NULL,
    day TEXT NOT NULL,
    type TEXT NOT NULL,
    note TEXT DEFAULT ''
)
""")

# Test cases
test_cases = {
    "TEST1": {
        "name": "Normal IN-OUT",
        "punches": [
            ("08:00:00", "IN"),
            ("09:00:00", "OUT"),
        ],
        "expected_warning": None,
    },
    "TEST2": {
        "name": "Duplicate IN",
        "punches": [
            ("08:00:00", "IN"),
            ("08:30:00", "IN"),
            ("09:00:00", "OUT"),
        ],
        "expected_warning": "Duplicate IN",
    },
    "TEST3": {
        "name": "OUT without IN",
        "punches": [
            ("08:00:00", "OUT"),
            ("08:15:00", "IN"),
            ("09:00:00", "OUT"),
        ],
        "expected_warning": "OUT without IN",
    },
    "TEST4": {
        "name": "Duplicate OUT",
        "punches": [
            ("08:00:00", "IN"),
            ("08:30:00", "OUT"),
            ("09:00:00", "OUT"),
        ],
        "expected_warning": "OUT without IN",
    },
    "TEST5": {
        "name": "Two valid sessions",
        "punches": [
            ("08:00:00", "IN"),
            ("08:30:00", "OUT"),
            ("09:00:00", "IN"),
            ("09:30:00", "OUT"),
        ],
        "expected_warning": None,
    },
}

# Insert test employees and punches
for emp_id, test in test_cases.items():
    con.execute(
        """
        INSERT INTO employees (emp_id, name, department, active, created_at)
        VALUES (?, ?, ?, ?, ?)
        """,
        (emp_id, test["name"], "TEST", 1, today),
    )

    for punch_time, event in test["punches"]:
        timestamp = f"{today} {punch_time}"

        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event, source, voided)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                emp_id,
                test["name"],
                timestamp,
                today,
                event,
                "kiosk",
                0,
            ),
        )

# Report settings
settings = {
    "office_start": "09:30",
    "grace_minutes": "10",
    "weekly_off": "Sunday",
}

# Run report against the temporary database
rows, summaries = build_report(
    con,
    date.fromisoformat(today),
    date.fromisoformat(today),
    settings,
)

# Validate results
print("\n========== ATTENDANCE VALIDATION TEST ==========\n")

for emp_id, test in test_cases.items():
    row = next(r for r in rows if r["emp_id"] == emp_id)

    note = row.get("note", "")
    expected = test["expected_warning"]

    if expected:
        passed = expected in note
    else:
        passed = "WARNING:" not in note

    print(f"Test: {test['name']}")
    print(f"Hours: {row.get('total_work_hours')}")
    print(f"Note: {note or 'None'}")
    print(f"Result: {'PASS' if passed else 'FAIL'}")
    print("-" * 40)

con.close()
