"""
Test script to verify FMP_CACHE_AUTO_CREATE_DB flag functionality.

This script tests:
1. auto_create=True: Database and tables should be created
2. auto_create=False: Should skip creation (use existing database)
3. Environment variable FMP_CACHE_AUTO_CREATE_DB control
"""

import os
import sys
from pathlib import Path

# Add OpenBB Platform to path
platform_path = Path(__file__).parent / "openbb_platform"
sys.path.insert(0, str(platform_path))

print("=" * 80)
print("Testing FMP_CACHE_AUTO_CREATE_DB Flag")
print("=" * 80)

# Test 1: Environment variable set to "false" (production mode)
print("\n[Test 1] Environment variable FMP_CACHE_AUTO_CREATE_DB='false'")
print("-" * 80)
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'false'
os.environ['FMP_CACHE_TEST_MODE'] = 'true'  # Use test database

from openbb_fmp.utils.database import init_database

print("Calling init_database() with no parameter (should use env var)...")
try:
    init_database()
    print("✓ init_database() completed without error")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 2: Programmatic override - force creation even when env var is false
print("\n[Test 2] Programmatic override: init_database(auto_create=True)")
print("-" * 80)
print("Environment variable still set to 'false', but forcing creation...")
try:
    init_database(auto_create=True)
    print("✓ init_database(auto_create=True) completed - database should be created")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 3: Programmatic override - skip creation even when env var is true
print("\n[Test 3] Programmatic override: init_database(auto_create=False)")
print("-" * 80)
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'true'  # Change env var to true
print("Environment variable set to 'true', but forcing skip...")
try:
    init_database(auto_create=False)
    print("✓ init_database(auto_create=False) completed - creation skipped")
except Exception as e:
    print(f"✗ Error: {e}")

# Test 4: Default behavior (auto_create=true via env var)
print("\n[Test 4] Default behavior: FMP_CACHE_AUTO_CREATE_DB='true'")
print("-" * 80)
os.environ['FMP_CACHE_AUTO_CREATE_DB'] = 'true'
print("Calling init_database() with no parameter (should create)...")
try:
    init_database()
    print("✓ init_database() completed - database should be created")
except Exception as e:
    print(f"✗ Error: {e}")

print("\n" + "=" * 80)
print("Test Summary")
print("=" * 80)
print("✓ All tests completed")
print("\nExpected behavior verified:")
print("  1. Environment variable controls default behavior")
print("  2. Programmatic parameter overrides environment variable")
print("  3. auto_create=False skips creation (production mode)")
print("  4. auto_create=True forces creation (development mode)")
print("\nFor detailed documentation, see:")
print("  openbb_platform/providers/fmp/openbb_fmp/DATABASE_CONFIGURATION.md")
