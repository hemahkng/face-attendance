import database as dbm

print("1. Initializing PostgreSQL database...")
dbm.init_db()
print("✅ Database initialized")

print("\n2. Testing settings read...")
with dbm.db() as con:
    settings = dbm.get_settings(con)
    print("Settings loaded:", len(settings))
    print("Company:", settings.get("company_name"))
    print("Office start:", settings.get("office_start"))

print("\n3. Testing setting write/read...")
with dbm.db() as con:
    dbm.set_setting(con, "database_test", "SUCCESS")

with dbm.db() as con:
    result = con.execute(
        "SELECT value FROM settings WHERE key = ?", ("database_test",)
    ).fetchone()

    print("Test value:", result["value"])

print("\n4. Cleaning test setting...")
with dbm.db() as con:
    con.execute("DELETE FROM settings WHERE key = ?", ("database_test",))

print("\n🎉 ALL DATABASE TESTS COMPLETED!")
