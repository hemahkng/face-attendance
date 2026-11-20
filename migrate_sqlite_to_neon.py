import sqlite3
from pathlib import Path

from sqlalchemy import text, insert
from db_connection import engine
from models import Employee, Attendance, Holiday, Leave, Setting

SQLITE_DB = Path("attendance.db")
BACKUP_DB = Path("attendance_before_neon_migration.db")

TABLES = [
    ("employees", Employee),
    ("attendance", Attendance),
    ("holidays", Holiday),
    ("leaves", Leave),
    ("settings", Setting),
]


def get_sqlite_data():
    if not SQLITE_DB.exists():
        raise FileNotFoundError(f"SQLite database not found: {SQLITE_DB}")

    if not BACKUP_DB.exists():
        raise FileNotFoundError("Migration backup not found. Aborting for safety.")

    sqlite_conn = sqlite3.connect(SQLITE_DB)
    sqlite_conn.row_factory = sqlite3.Row

    data = {}

    try:
        for table_name, model in TABLES:
            rows = sqlite_conn.execute(f'SELECT * FROM "{table_name}"').fetchall()

            data[table_name] = [dict(row) for row in rows]

    finally:
        sqlite_conn.close()

    return data


def migrate():
    print("=" * 50)
    print("FACENEX - SQLite to Neon Migration")
    print("=" * 50)

    print("\n1. Reading SQLite database...")
    source_data = get_sqlite_data()

    for table_name, rows in source_data.items():
        print(f"   SQLite {table_name}: {len(rows)} records")

    print("\n2. Checking Neon database...")

    with engine.begin() as conn:
        # Safety check: all destination tables must be empty.
        for table_name, model in TABLES:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{table_name}"')).scalar()

            print(f"   Neon {table_name}: {count} records")

            if count != 0:
                raise RuntimeError(
                    f"Neon table '{table_name}' is not empty. Migration cancelled."
                )

        print("\n3. Migrating records...")

        # Insert in a single transaction.
        for table_name, model in TABLES:
            rows = source_data[table_name]

            if not rows:
                print(f"   {table_name}: skipped (empty)")
                continue

            conn.execute(insert(model), rows)

            print(f"   {table_name}: {len(rows)} records inserted")

        # Reset auto-increment sequences for tables with integer IDs.
        for table_name, column_name in [
            ("attendance", "id"),
            ("leaves", "id"),
        ]:
            sequence_name = conn.execute(
                text("SELECT pg_get_serial_sequence(:table_name, :column_name)"),
                {
                    "table_name": table_name,
                    "column_name": column_name,
                },
            ).scalar()

            if sequence_name:
                conn.execute(
                    text(
                        """
                        SELECT setval(
                            :sequence_name,
                            COALESCE(
                                (SELECT MAX(id) FROM """
                        + table_name
                        + """),
                                1
                            ),
                            (SELECT COUNT(*) > 0 FROM """
                        + table_name
                        + """)
                        )
                        """
                    ),
                    {"sequence_name": sequence_name},
                )

        print("\n4. Verifying migrated record counts...")

        for table_name, model in TABLES:
            source_count = len(source_data[table_name])

            destination_count = conn.execute(
                text(f'SELECT COUNT(*) FROM "{table_name}"')
            ).scalar()

            print(f"   {table_name}: SQLite={source_count}, Neon={destination_count}")

            if source_count != destination_count:
                raise RuntimeError(
                    f"Count mismatch in {table_name}! Transaction will be rolled back."
                )

    print("\n" + "=" * 50)
    print("MIGRATION COMPLETED SUCCESSFULLY!")
    print("All records migrated and verified.")
    print("Original SQLite database remains unchanged.")
    print("=" * 50)


if __name__ == "__main__":
    migrate()
