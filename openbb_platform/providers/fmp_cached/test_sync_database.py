"""
Test script to verify synchronous database operations work correctly.
Run this in Jupyter notebook or as a regular Python script.
"""

# Test import and basic functionality
from openbb_platform.providers.fmp_cached.openbb_fmp_cached.utils.database import (
    execute_query,
    execute_many,
    init_database,
    get_connection_pool
)

print("✅ Successfully imported synchronous database utilities")

# Test 1: Connection pool creation
try:
    pool = get_connection_pool()
    print("✅ Connection pool created successfully")
except Exception as e:
    print(f"❌ Connection pool creation failed: {e}")

# Test 2: Simple query execution
try:
    result = execute_query("SELECT 1 as test")
    print(f"✅ Simple query executed successfully: {result}")
except Exception as e:
    print(f"❌ Simple query failed: {e}")

# Test 3: Database initialization
try:
    init_result = init_database()
    print(f"✅ Database initialization successful: {init_result}")
except Exception as e:
    print(f"❌ Database initialization failed: {e}")

# Test 4: Table query
try:
    tables = execute_query("SHOW TABLES")
    print(f"✅ Table listing successful: Found {len(tables)} tables")
except Exception as e:
    print(f"❌ Table listing failed: {e}")

print("\n" + "="*50)
print("🎉 All synchronous database tests completed!")
print("="*50)
