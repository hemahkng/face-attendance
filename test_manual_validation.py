import tempfile
from pathlib import Path
from datetime import date, timedelta

import database as dbm
from app import add_punch, PunchBody
from fastapi import HTTPException

# Create a temporary database for testing
temp_db = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
temp_db.close()

original_db_path = dbm.DB_PATH
dbm.DB_PATH = Path(temp_db.name)

try:
    dbm.init_db()

    test_day = (date.today() - timedelta(days=1)).isoformat()

    # Create test employee
    with dbm.db() as con:
        con.execute(
            """
            INSERT INTO employees
            (emp_id, name, embedding, department, active)
            VALUES (?, ?, ?, ?, ?)
            """,
            ("TEST001", "Validation Test", bytes(2048), "TEST", 1),
        )

    def punch(event, time):
        return PunchBody(
            emp_id="TEST001",
            day=test_day,
            time=time,
            event=event,
            reason="Testing validation",
        )

    def run_test(name, event, time, expected):
        print(f"\nTest: {name}")

        try:
            result = add_punch(punch(event, time))
            print("Response:", result)
            passed = expected == "OK"

        except HTTPException as exc:
            print("Rejected:", exc.detail)
            passed = expected == "REJECT"

        print("Result:", "PASS" if passed else "FAIL")
        print("-" * 40)

    # Test 1: Valid IN
    run_test("First IN", "IN", "09:00", "OK")

    # Test 2: Duplicate IN should be rejected
    run_test("Duplicate IN", "IN", "09:15", "REJECT")

    # Test 3: Valid OUT
    run_test("Valid OUT", "OUT", "09:30", "OK")

    # Test 4: Duplicate OUT should be rejected
    run_test("Duplicate OUT", "OUT", "09:45", "REJECT")

    # Test 5: New IN after OUT is valid
    run_test("Second IN", "IN", "10:00", "OK")

    # Test 6: OUT closes the second session
    run_test("Second OUT", "OUT", "10:30", "OK")

    # Test 7: Backdated duplicate IN
    run_test("Backdated duplicate IN", "IN", "09:15", "REJECT")

    # Test 8: Valid OUT on separate day
    print("\nTest: Valid OUT on separate day")

    test_day2 = (date.today() - timedelta(days=2)).isoformat()

    with dbm.db() as con:
        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "TEST001",
                "Validation Test",
                f"{test_day2} 09:00:00",
                test_day2,
                "IN",
            ),
        )

    try:
        result = add_punch(
            PunchBody(
                emp_id="TEST001",
                day=test_day2,
                time="09:30",
                event="OUT",
                reason="Testing valid OUT",
            )
        )
        print("Response:", result)
        print("Result: PASS")

    except HTTPException as exc:
        print("Rejected:", exc.detail)
        print("Result: FAIL")

    print("-" * 40)

    # Test 9: Backdated OUT fixes sequence
    print("\nTest: Backdated OUT fixes sequence")

    test_day3 = (date.today() - timedelta(days=3)).isoformat()

    with dbm.db() as con:
        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "TEST001",
                "Validation Test",
                f"{test_day3} 09:00:00",
                test_day3,
                "IN",
            ),
        )

        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "TEST001",
                "Validation Test",
                f"{test_day3} 12:00:00",
                test_day3,
                "IN",
            ),
        )

    try:
        result = add_punch(
            PunchBody(
                emp_id="TEST001",
                day=test_day3,
                time="10:00",
                event="OUT",
                reason="Adding missing backdated OUT",
            )
        )
        print("Response:", result)
        print("Result: PASS")

    except HTTPException as exc:
        print("Rejected:", exc.detail)
        print("Result: FAIL")

    print("-" * 40)

    # Test 10: Same-time IN and OUT must be rejected
    print("\nTest: Same-time IN and OUT")

    test_day4 = (date.today() - timedelta(days=4)).isoformat()

    with dbm.db() as con:
        con.execute(
            """
            INSERT INTO attendance
            (emp_id, name, timestamp, date, event)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "TEST001",
                "Validation Test",
                f"{test_day4} 09:00:00",
                test_day4,
                "IN",
            ),
        )

    try:
        result = add_punch(
            PunchBody(
                emp_id="TEST001",
                day=test_day4,
                time="09:00",
                event="OUT",
                reason="Testing same-time punches",
            )
        )
        print("Response:", result)
        print("Result: FAIL (same-time punch was accepted)")

    except HTTPException as exc:
        print("Rejected:", exc.detail)

        if exc.status_code == 409:
            print("Result: PASS")
        else:
            print("Result: FAIL (unexpected error code)")

    print("-" * 40)

finally:
    # Restore original database path
    dbm.DB_PATH = original_db_path

    # Remove temporary test database
    try:
        Path(temp_db.name).unlink(missing_ok=True)
    except Exception:
        pass

print("\nManual attendance validation test completed.")
