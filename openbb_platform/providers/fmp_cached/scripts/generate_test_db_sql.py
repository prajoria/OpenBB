#!/usr/bin/env python3
"""
Generate SQL commands for MySQL admin to create test database.
This script creates the exact SQL commands needed to set up the test database.
"""

import json
from pathlib import Path


def load_db_config():
    """Load database configuration from OpenBB user settings."""
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    if not settings_path.exists():
        print("❌ OpenBB user settings file not found")
        return None
    
    try:
        with open(settings_path, 'r') as f:
            settings = json.load(f)
            credentials = settings.get("credentials", {})
            
            config = {
                "host": credentials.get("mysql_host", "localhost"),
                "port": int(credentials.get("mysql_port", 3306)),
                "user": credentials.get("mysql_user"),
                "password": credentials.get("mysql_password"),
                "database": credentials.get("mysql_database", "openbb_fmp_cache")
            }
            
            if not config["user"] or not config["password"]:
                print("❌ MySQL user or password not found in OpenBB user settings")
                return None
                
            return config
    except Exception as e:
        print(f"❌ Error loading OpenBB user settings: {e}")
        return None


def generate_sql_commands():
    """Generate SQL commands for database setup."""
    config = load_db_config()
    if not config:
        return False
    
    print("🔧 FMP Cached Provider - Test Database Setup")
    print("=" * 55)
    print(f"Configuration:")
    print(f"  Host: {config['host']}:{config['port']}")
    print(f"  User: {config['user']}")
    print(f"  Main DB: {config['database']}")
    print(f"  Test DB: openbb_fmp_cache_test")
    print()
    
    print("📋 SQL Commands for MySQL Admin:")
    print("=" * 40)
    print("-- Copy and paste these commands into MySQL as root or admin user:")
    print()
    print(f"CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test;")
    print(f"GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO '{config['user']}'@'localhost';")
    print(f"FLUSH PRIVILEGES;")
    print()
    
    print("📋 Alternative: Command Line")
    print("=" * 40)
    print("Run this command in terminal (as MySQL admin):")
    print()
    print(f'''mysql -u root -p -e "CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test; GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO '{config['user']}'@'localhost'; FLUSH PRIVILEGES;"''')
    print()
    
    print("📋 Verification Commands:")
    print("=" * 40)
    print("After running the setup commands, verify with:")
    print()
    print(f"mysql -u {config['user']} -p -e 'SHOW DATABASES;'")
    print(f"mysql -u {config['user']} -p openbb_fmp_cache_test -e 'SELECT 1;'")
    print()
    
    # Create SQL file for easy execution
    sql_file = "create_test_database.sql"
    with open(sql_file, 'w') as f:
        f.write(f"-- FMP Cached Provider Test Database Setup\n")
        f.write(f"-- Run as MySQL admin/root user\n\n")
        f.write(f"CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test;\n")
        f.write(f"GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO '{config['user']}'@'localhost';\n")
        f.write(f"FLUSH PRIVILEGES;\n\n")
        f.write(f"-- Verification\n")
        f.write(f"SHOW DATABASES;\n")
        f.write(f"SELECT User, Host FROM mysql.user WHERE User = '{config['user']}';\n")
    
    print(f"💾 SQL commands saved to: {sql_file}")
    print(f"   Run with: mysql -u root -p < {sql_file}")
    print()
    
    print("🎯 Next Steps:")
    print("1. Run the SQL commands above as MySQL admin")
    print("2. Test with: FMP_CACHE_TEST_MODE=true python tests/test_database_config.py")
    print("3. Use the FMP cached provider with test database")
    
    return True


if __name__ == "__main__":
    success = generate_sql_commands()
    exit(0 if success else 1)