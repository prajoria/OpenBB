#!/usr/bin/env python3
"""Simple MySQL connection test."""

import asyncio
import aiomysql
import sys

async def test_mysql_connection():
    """Test basic MySQL connection."""
    print("🔍 Testing MySQL connection...")
    
    try:
        # Try to connect to MySQL server (without specific database)
        connection = await aiomysql.connect(
            host="localhost",
            port=3306,
            user="root",  # We'll test with root first
        )
        
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT VERSION()")
            version = await cursor.fetchone()
            print(f"✅ MySQL server is running: {version[0]}")
            
        await connection.ensure_closed()
        return True
        
    except Exception as e:
        print(f"❌ MySQL connection failed: {e}")
        print("\n💡 Possible solutions:")
        print("   1. Install MySQL: sudo apt install mysql-server")
        print("   2. Start MySQL: sudo systemctl start mysql")
        print("   3. Check if MySQL is running: sudo systemctl status mysql")
        return False

async def check_database_exists():
    """Check if our database exists."""
    print("🔍 Checking if database exists...")
    
    try:
        connection = await aiomysql.connect(
            host="localhost",
            port=3306,
            user="root",
        )
        
        async with connection.cursor() as cursor:
            await cursor.execute("SHOW DATABASES LIKE 'openbb_fmp_cache'")
            result = await cursor.fetchone()
            
            if result:
                print("✅ Database 'openbb_fmp_cache' exists")
                exists = True
            else:
                print("❌ Database 'openbb_fmp_cache' does not exist")
                exists = False
                
        await connection.ensure_closed()
        return exists
        
    except Exception as e:
        print(f"❌ Database check failed: {e}")
        return False

async def check_user_exists():
    """Check if our user exists."""
    print("🔍 Checking if user exists...")
    
    try:
        connection = await aiomysql.connect(
            host="localhost",
            port=3306,
            user="root",
        )
        
        async with connection.cursor() as cursor:
            await cursor.execute("SELECT User FROM mysql.user WHERE User = 'fmp_user'")
            result = await cursor.fetchone()
            
            if result:
                print("✅ User 'fmp_user' exists")
                exists = True
            else:
                print("❌ User 'fmp_user' does not exist")
                exists = False
                
        await connection.ensure_closed()
        return exists
        
    except Exception as e:
        print(f"❌ User check failed: {e}")
        return False

async def main():
    """Run all checks."""
    print("🚀 MySQL Environment Check")
    print("=" * 30)
    
    # Test MySQL connection
    mysql_running = await test_mysql_connection()
    
    if not mysql_running:
        print("\n❌ MySQL is not running or not accessible")
        return False
    
    # Check database
    db_exists = await check_database_exists()
    
    # Check user
    user_exists = await check_user_exists()
    
    print(f"\n📊 Status Summary:")
    print(f"   MySQL Server: {'✅' if mysql_running else '❌'}")
    print(f"   Database: {'✅' if db_exists else '❌'}")
    print(f"   User: {'✅' if user_exists else '❌'}")
    
    if not db_exists or not user_exists:
        print(f"\n🎯 Next Steps:")
        print(f"   Run: python setup_database.py")
        print(f"   This will create the missing database and user")
    
    return mysql_running and db_exists and user_exists

if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)