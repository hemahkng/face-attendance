from sqlalchemy import inspect, text
from db_connection import engine

inspector = inspect(engine)

print("=== FACENEX NEON DATABASE VERIFICATION ===")

tables = inspector.get_table_names()
print("\nTables found:", tables)

with engine.connect() as conn:
    for table in ["employees", "attendance", "holidays", "leaves", "settings"]:
        if table in tables:
            count = conn.execute(text(f'SELECT COUNT(*) FROM "{table}"')).scalar()

            print(f"{table}: {count} records")

print("\n✅ Verification completed.")
