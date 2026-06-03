#!/usr/bin/env python3
"""Test script for FMP Cached provider."""

import asyncio
import json
import os
import time
from datetime import datetime, timedelta, date
from pathlib import Path

def test_configuration():
    """Test if configuration is properly set up."""
    print("Testing configuration...")
    
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    if not settings_path.exists():
        print("❌ OpenBB user settings file not found")
        print("💡 Run configure_mysql.py to set up MySQL credentials")
        return False
    
    with open(settings_path, 'r') as f:
        settings = json.load(f)
    
    credentials = settings.get("credentials", {})
    
    # Check FMP API key
    if not credentials.get("fmp_api_key"):
        print("❌ FMP API key not found in settings")
        print("💡 Add your FMP API key to OpenBB user settings")
        return False
    
    # Check MySQL settings in OpenBB user settings
    mysql_keys = ["mysql_host", "mysql_port", "mysql_user", "mysql_password", "mysql_database"]
    missing_keys = [key for key in mysql_keys if not credentials.get(key)]
    
    if missing_keys:
        print(f"❌ Missing MySQL configuration in OpenBB user settings: {missing_keys}")
        print("💡 Run configure_mysql.py to set up MySQL credentials")
        return False
    
    print("✅ Configuration found in OpenBB user settings")
    print(f"   • FMP API key: {'*' * len(credentials.get('fmp_api_key', ''))}")
    print(f"   • MySQL host: {credentials.get('mysql_host')}")
    print(f"   • MySQL user: {credentials.get('mysql_user')}")
    print(f"   • MySQL database: {credentials.get('mysql_database')}")
    return True

async def test_database_connection():
    """Test database connection."""
    print("Testing database connection...")
    
    try:
        from openbb_fmp_cached.utils.database import get_connection_pool
        
        pool = get_connection_pool()
        async with pool.get_connection() as conn:
            async with conn.cursor() as cursor:
                await cursor.execute("SELECT 1")
                result = await cursor.fetchone()
                if result and result[0] == 1:
                    print("✅ Database connection successful")
                    return True
    except Exception as e:
        print(f"❌ Database connection failed: {e}")
        return False
    
    return False

async def test_cache_operations():
    """Test cache storage and retrieval."""
    print("Testing cache operations...")
    
    try:
        from openbb_fmp_cached.utils.cache_manager import get_cache_manager, generate_cache_key
        from openbb_fmp_cached.utils.database import init_database
        
        # Initialize database
        await init_database()
        
        cache_manager = get_cache_manager()
        
        # Test data
        test_data = [{"symbol": "AAPL", "price": 150.0, "date": "2024-01-01"}]
        cache_key = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d")
        
        # Store data
        success = await cache_manager.store_cached_data(
            "EquityHistorical", cache_key, test_data, symbol="AAPL", interval="1d"
        )
        
        if not success:
            print("❌ Failed to store test data in cache")
            return False
        
        # Retrieve data
        cached_data = await cache_manager.get_cached_data(
            "EquityHistorical", cache_key, symbol="AAPL", interval="1d"
        )
        
        if cached_data != test_data:
            print("❌ Cached data doesn't match original data")
            return False
        
        print("✅ Cache operations working correctly")
        return True
        
    except Exception as e:
        print(f"❌ Cache operations failed: {e}")
        return False

def test_provider_import():
    """Test if provider can be imported."""
    print("Testing provider import...")
    
    try:
        from openbb_fmp_cached import fmp_cached_provider
        
        if fmp_cached_provider.name != "fmp_cached":
            print("❌ Provider name incorrect")
            return False
        
        # Check that fetchers are created
        if len(fmp_cached_provider.fetcher_dict) == 0:
            print("❌ No fetchers found in provider")
            return False
        
        print(f"✅ Provider imported successfully with {len(fmp_cached_provider.fetcher_dict)} fetchers")
        return True
        
    except Exception as e:
        print(f"❌ Provider import failed: {e}")
        return False

async def test_openbb_integration():
    """Test integration with OpenBB Platform."""
    print("Testing OpenBB Platform integration...")
    
    try:
        from openbb import obb
        
        # This should work if the provider is properly installed
        start_date = (datetime.now() - timedelta(days=5)).date()
        end_date = (datetime.now() - timedelta(days=1)).date()
        
        result = obb.equity.price.historical(
            "AAPL", 
            start_date=start_date,
            end_date=end_date,
            provider="fmp_cached"
        )
        
        if result is None:
            print("❌ No data returned from OpenBB")
            return False
        
        df = result.to_df()
        if df.empty:
            print("❌ Empty DataFrame returned")
            return False
        
        print(f"✅ OpenBB integration working - got {len(df)} rows of data")
        return True
        
    except Exception as e:
        print(f"❌ OpenBB integration failed: {e}")
        print("This might be expected if OpenBB doesn't have the provider registered yet")
        return False

async def performance_test():
    """Test cache performance."""
    print("Testing cache performance...")
    
    try:
        from openbb_fmp_cached.utils.cache_manager import get_cache_manager, generate_cache_key
        
        cache_manager = get_cache_manager()
        
        # Generate test data
        test_data = [
            {"symbol": "AAPL", "date": f"2024-01-{i:02d}", "close": 150 + i}
            for i in range(1, 101)
        ]
        
        cache_key = generate_cache_key("EquityHistorical", symbol="AAPL", interval="1d", test="performance")
        
        # Time cache write
        start_time = time.time()
        await cache_manager.store_cached_data(
            "EquityHistorical", cache_key, test_data, symbol="AAPL", interval="1d"
        )
        write_time = time.time() - start_time
        
        # Time cache read
        start_time = time.time()
        cached_data = await cache_manager.get_cached_data(
            "EquityHistorical", cache_key, symbol="AAPL", interval="1d"
        )
        read_time = time.time() - start_time
        
        if cached_data != test_data:
            print("❌ Performance test data mismatch")
            return False
        
        print(f"✅ Performance test passed:")
        print(f"   Write time: {write_time:.4f}s")
        print(f"   Read time: {read_time:.4f}s")
        print(f"   Data size: {len(test_data)} records")
        
        # Print cache stats
        stats = cache_manager.get_stats()
        print(f"   Cache stats: {stats}")
        
        return True
        
    except Exception as e:
        print(f"❌ Performance test failed: {e}")
        return False

async def run_all_tests():
    """Run all tests."""
    print("🧪 FMP Cached Provider Test Suite")
    print("=" * 50)
    
    tests = [
        ("Configuration", test_configuration),
        ("Database Connection", test_database_connection),
        ("Cache Operations", test_cache_operations),
        ("Provider Import", test_provider_import),
        ("OpenBB Integration", test_openbb_integration),
        ("Performance", performance_test)
    ]
    
    results = []
    
    for test_name, test_func in tests:
        print(f"\n🔍 Running {test_name} test...")
        try:
            if asyncio.iscoroutinefunction(test_func):
                result = await test_func()
            else:
                result = test_func()
            results.append((test_name, result))
        except Exception as e:
            print(f"❌ {test_name} test crashed: {e}")
            results.append((test_name, False))
    
    # Print summary
    print("\n📊 Test Results Summary")
    print("=" * 50)
    
    passed = 0
    for test_name, result in results:
        status = "✅ PASS" if result else "❌ FAIL"
        print(f"{test_name:20} {status}")
        if result:
            passed += 1
    
    print(f"\nOverall: {passed}/{len(results)} tests passed")
    
    if passed == len(results):
        print("🎉 All tests passed! FMP Cached provider is ready to use.")
    else:
        print("⚠️ Some tests failed. Check the errors above.")
    
    return passed == len(results)

if __name__ == "__main__":
    success = asyncio.run(run_all_tests())
    exit(0 if success else 1)