#!/usr/bin/env python3
"""MySQL database setup script for FMP Cached provider."""

import asyncio
import aiomysql
import json
import os
import sys
from pathlib import Path

def load_db_config():
    """Load database configuration from OpenBB user settings."""
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    # Base configuration; user/password have no hardcoded defaults and must
    # come from user_settings.json or the DB_USER/DB_PASSWORD env vars.
    config = {
        "host": "localhost",
        "port": 3306,
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
        "database": "openbb_fmp_cache"
    }

    try:
        if settings_path.exists():
            with open(settings_path, 'r') as f:
                settings = json.load(f)
                credentials = settings.get("credentials", {})

                config.update({
                    "host": credentials.get("mysql_host", config["host"]),
                    "port": int(credentials.get("mysql_port", config["port"])),
                    "user": credentials.get("mysql_user", config["user"]),
                    "password": credentials.get("mysql_password", config["password"]),
                    "database": credentials.get("mysql_database", config["database"])
                })
    except Exception as e:
        print(f"⚠️  Could not load OpenBB settings: {e}")

    missing = [n for n in ("user", "password") if not config.get(n)]
    if missing:
        raise ValueError(
            f"Missing MySQL credential(s): {', '.join(missing)}. Set them in "
            "~/.openbb_platform/user_settings.json or DB_USER/DB_PASSWORD."
        )

    return config

# Load database configuration
db_config = load_db_config()
DB_HOST = db_config["host"]
DB_PORT = db_config["port"]
DB_USER = db_config["user"]
DB_PASSWORD = db_config["password"]
DB_NAME = db_config["database"]

async def create_database_and_user():
    """Create database and user if they don't exist."""
    print("🗄️  Setting up MySQL database for FMP Cached provider...")
    
    # Try to connect as the existing user first to create test database
    print(f"Trying to create test database using existing user '{DB_USER}'...")
    
    try:
        # Connect as existing user
        connection = await aiomysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD
        )
        
        async with connection.cursor() as cursor:
            # Try to create test database
            test_db_name = "openbb_fmp_cache_test"
            print(f"Creating test database '{test_db_name}' if it doesn't exist...")
            try:
                await cursor.execute(f"CREATE DATABASE IF NOT EXISTS `{test_db_name}`")
                print(f"✅ Test database '{test_db_name}' created successfully!")
            except Exception as db_error:
                print(f"⚠️  Could not create test database: {db_error}")
                print(f"💡 You may need to ask your MySQL admin to create '{test_db_name}' database")
                print(f"    and grant privileges to user '{DB_USER}'")
                
                # Check if the database already exists
                await cursor.execute("SHOW DATABASES")
                databases = await cursor.fetchall()
                db_list = [db[0] for db in databases]
                
                if test_db_name in db_list:
                    print(f"✅ Test database '{test_db_name}' already exists!")
                else:
                    await connection.ensure_closed()
                    return False
            
        await connection.ensure_closed()
        print("✅ Database and user created successfully!")
        
    except Exception as e:
        print(f"❌ Error setting up database: {e}")
        print("Please make sure MySQL is running and you have the correct root password.")
        return False
    
    return True

async def test_connection():
    """Test connection with both main and test databases."""
    print(f"🔍 Testing database connections as user '{DB_USER}'...")
    
    # Test main database
    try:
        connection = await aiomysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=DB_NAME
        )
        
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            result = await cursor.fetchone()
            if result and result[0] == 1:
                print(f"✅ Main database '{DB_NAME}' connection: SUCCESS")
            await connection.ensure_closed()
                
    except Exception as e:
        print(f"❌ Main database '{DB_NAME}' connection: FAILED - {e}")
        return False
    
    # Test test database
    try:
        test_db_name = "openbb_fmp_cache_test"
        connection = await aiomysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            db=test_db_name
        )
        
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT 1")
            result = await cursor.fetchone()
            if result and result[0] == 1:
                print(f"✅ Test database '{test_db_name}' connection: SUCCESS")
            await connection.ensure_closed()
                
    except Exception as e:
        print(f"❌ Test database '{test_db_name}' connection: FAILED - {e}")
        return False
    
    return True

def create_cache_tables():
    """Create the cache tables."""
    print("🗂️  Creating cache tables...")

    try:
        # Add the provider to Python path
        sys.path.append(str(Path(__file__).parent))

        from openbb_fmp_cached.utils.database import init_database
        from openbb_fmp_cached.utils.cache_schema import create_all_tables

        # Initialize database and create tables.
        # NOTE: init_database and create_all_tables are SYNCHRONOUS
        # (they return bool / dict, not coroutines). Awaiting them
        # raised `TypeError: object bool can't be used in 'await'
        # expression` — see #775.
        init_database()
        create_all_tables()

        print("✅ Cache tables created successfully!")
        return True

    except Exception as e:
        print(f"❌ Error creating cache tables: {e}")
        return False

def verify_user_settings():
    """Verify that user settings have MySQL configuration."""
    print("📝 Verifying OpenBB user settings...")
    
    try:
        settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
        
        if not settings_path.exists():
            print("❌ OpenBB user settings file not found")
            print("💡 Run configure_mysql.py first to set up MySQL credentials")
            return False
            
        with open(settings_path, 'r') as f:
            settings = json.load(f)
            
        credentials = settings.get("credentials", {})
        mysql_keys = ["mysql_host", "mysql_user", "mysql_password", "mysql_database"]
        missing_keys = [key for key in mysql_keys if key not in credentials]
        
        if missing_keys:
            print(f"❌ Missing MySQL configuration in user settings: {missing_keys}")
            print("💡 Run configure_mysql.py to set up MySQL credentials")
            return False
        
        print("✅ MySQL configuration found in OpenBB user settings")
        return True
        
    except Exception as e:
        print(f"❌ Error verifying user settings: {e}")
        return False

async def main():
    """Main setup function."""
    print("🚀 FMP Cached Provider Database Setup")
    print("=" * 50)
    print(f"Database: {DB_NAME}")
    print(f"User: {DB_USER}")
    print(f"Host: {DB_HOST}:{DB_PORT}")
    print()
    
    # Step 1: Create database and user
    if not await create_database_and_user():
        print("❌ Database setup failed!")
        return False
    
    # Step 2: Test connection
    if not await test_connection():
        print("❌ Connection test failed!")
        return False
    
    # Step 3: Verify user settings
    if not verify_user_settings():
        print("❌ User settings verification failed!")
        print("💡 Run configure_mysql.py first to set up MySQL credentials")
        return False
    
    # Step 4: Create cache tables (sync call — see note in create_cache_tables)
    if not create_cache_tables():
        print("❌ Cache tables creation failed!")
        return False
    
    print("\n🎉 Database setup completed successfully!")
    print("\n📋 What was created:")
    print(f"   • MySQL database: {DB_NAME}")
    print(f"   • MySQL user: {DB_USER}")
    print(f"   • Cache tables: 6 specialized tables")
    print(f"   • Configuration: Read from OpenBB user settings")
    
    print("\n🎯 Next steps:")
    print("   1. Run: python test_fmp_cached.py")
    print("   2. Test the provider in your code")
    
    return True

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)