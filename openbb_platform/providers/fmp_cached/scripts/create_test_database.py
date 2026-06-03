#!/usr/bin/env python3
"""
Simple script to create test database using existing user credentials.
This assumes the MySQL user already has CREATE DATABASE privileges.
"""

import asyncio
import aiomysql
import json
import os
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


async def create_test_database():
    """Create test database using existing user credentials."""
    print("🧪 Creating Test Database for FMP Cached Provider")
    print("=" * 55)
    
    config = load_db_config()
    if not config:
        return False
    
    print(f"📋 Configuration:")
    print(f"   Host: {config['host']}:{config['port']}")
    print(f"   User: {config['user']}")
    print(f"   Main DB: {config['database']}")
    print(f"   Test DB: openbb_fmp_cache_test")
    print()
    
    try:
        # Connect to MySQL server (without specifying database)
        connection = await aiomysql.connect(
            host=config["host"],
            port=config["port"],
            user=config["user"],
            password=config["password"]
        )
        
        async with connection.cursor() as cursor:
            # Create test database
            test_db_name = "openbb_fmp_cache_test"
            print(f"🗄️  Creating database '{test_db_name}'...")
            
            await cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{test_db_name}`")
            print(f"✅ Database '{test_db_name}' created successfully!")
            
            # Check if we have access to both databases
            await cursor.execute("SHOW DATABASES")
            databases = await cursor.fetchall()
            db_list = [db[0] for db in databases]
            
            main_db_exists = config['database'] in db_list
            test_db_exists = test_db_name in db_list
            
            print(f"📊 Database Status:")
            print(f"   {config['database']}: {'✅ EXISTS' if main_db_exists else '❌ NOT FOUND'}")
            print(f"   {test_db_name}: {'✅ EXISTS' if test_db_exists else '❌ NOT FOUND'}")
            
        await connection.ensure_closed()
        
        # Test connections to both databases
        print(f"\n🔍 Testing Database Connections:")
        
        # Test main database
        try:
            conn = await aiomysql.connect(**config)
            await conn.ensure_closed()
            print(f"   {config['database']}: ✅ CONNECTION OK")
        except Exception as e:
            print(f"   {config['database']}: ❌ CONNECTION FAILED - {e}")
        
        # Test test database
        try:
            test_config = config.copy()
            test_config["database"] = test_db_name
            conn = await aiomysql.connect(**test_config)
            await conn.ensure_closed()
            print(f"   {test_db_name}: ✅ CONNECTION OK")
        except Exception as e:
            print(f"   {test_db_name}: ❌ CONNECTION FAILED - {e}")
        
        print(f"\n🎉 Test database setup completed!")
        print(f"\n💡 Usage:")
        print(f"   Normal mode: python tests/test_database_config.py")
        print(f"   Test mode: FMP_CACHE_TEST_MODE=true python tests/test_database_config.py")
        
        return True
        
    except aiomysql.Error as e:
        print(f"❌ MySQL Error: {e}")
        if "Access denied" in str(e):
            print("💡 The user may not have CREATE DATABASE privileges.")
            print("   Ask your MySQL administrator to create 'openbb_fmp_cache_test' database")
            print("   and grant privileges to your user.")
        return False
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


def print_manual_setup_instructions():
    """Print manual setup instructions."""
    config = load_db_config()
    if not config:
        return
    
    print(f"\n📋 Manual Setup Instructions (if automatic creation fails):")
    print(f"=" * 60)
    print(f"Run these commands in MySQL as a user with CREATE DATABASE privileges:")
    print(f"")
    print(f"  CREATE DATABASE IF NOT EXISTS openbb_fmp_cache_test;")
    print(f"  GRANT ALL PRIVILEGES ON openbb_fmp_cache_test.* TO '{config['user']}'@'localhost';")
    print(f"  FLUSH PRIVILEGES;")
    print(f"")
    print(f"Or ask your MySQL administrator to run them.")


async def main():
    """Main function."""
    success = await create_test_database()
    
    if not success:
        print_manual_setup_instructions()
    
    return success


if __name__ == "__main__":
    success = asyncio.run(main())
    exit(0 if success else 1)