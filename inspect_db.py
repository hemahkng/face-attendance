import sqlite3

DB_PATH = "attendance.db"

conn = sqlite3.connect(DB_PATH)
cursor = conn.cursor()

tables = cursor.execute("""
    SELECT name
    FROM sqlite_master
    WHERE type = 'table'
      AND name NOT LIKE 'sqlite_%'
    ORDER BY name
""").fetchall()

print("\n========== FACENEX DATABASE STRUCTURE ==========\n")

for (table_name,) in tables:
    print(f"\n📁 TABLE: {table_name}")
    print("-" * 50)

    columns = cursor.execute(f'PRAGMA table_info("{table_name}")').fetchall()

    for column in columns:
        cid, name, data_type, notnull, default_value, pk = column

        print(f"  {name:<25} {data_type:<15} PK={pk} NOT_NULL={notnull}")

    count = cursor.execute(f'SELECT COUNT(*) FROM "{table_name}"').fetchone()[0]

    print(f"  Total records: {count}")

conn.close()

print("\n========== INSPECTION COMPLETE ==========\n")
