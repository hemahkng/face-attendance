from db_connection import engine
from models import Base

print("Creating FACENEX PostgreSQL tables...")

Base.metadata.create_all(bind=engine)

print("✅ Tables created successfully!")
print("\nTables:")
for table in Base.metadata.sorted_tables:
    print(f" - {table.name}")
