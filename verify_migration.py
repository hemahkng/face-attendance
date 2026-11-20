import sqlite3
import hashlib
from sqlalchemy import text
from db_connection import engine

sqlite_conn = sqlite3.connect("attendance.db")

print("=== FACENEX MIGRATION INTEGRITY CHECK ===")

# Get original employee embeddings from SQLite
source = sqlite_conn.execute("SELECT emp_id, name, embedding FROM employees").fetchall()

with engine.connect() as conn:
    destination = conn.execute(
        text("SELECT emp_id, name, embedding FROM employees")
    ).fetchall()

print("\nEmployee comparison:")

for source_emp in source:
    emp_id, name, source_embedding = source_emp

    destination_emp = next((e for e in destination if e.emp_id == emp_id), None)

    if destination_emp is None:
        print(f"❌ Missing employee: {emp_id}")
        continue

    source_hash = hashlib.sha256(source_embedding).hexdigest()
    destination_hash = hashlib.sha256(bytes(destination_emp.embedding)).hexdigest()

    print(f"\nEmployee: {name} ({emp_id})")
    print(f"SQLite embedding size: {len(source_embedding)} bytes")
    print(f"Neon embedding size: {len(destination_emp.embedding)} bytes")
    print(f"SQLite SHA256: {source_hash}")
    print(f"Neon SHA256:   {destination_hash}")

    if source_hash == destination_hash:
        print("✅ Face embedding is identical")
    else:
        print("❌ Embedding mismatch!")

sqlite_conn.close()

print("\nIntegrity check completed.")
