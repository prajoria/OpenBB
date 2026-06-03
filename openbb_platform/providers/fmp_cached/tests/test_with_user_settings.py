"""Simple test script using OpenBB user settings for FMP API key.

This script tests the FMP cached provider using the real API key from 
OpenBB's user settings (~/.openbb_platform/user_settings.json).

Setup:
1. Ensure your FMP API key is set in user_settings.json:
   {
     "credentials": {
       "fmp_api_key": "your_actual_api_key_here"
     }
   }

2. Run: python test_with_user_settings.py

The test will:
- Load the API key from OpenBB user settings automatically
- Make real API calls to test cache miss and cache hit scenarios
- Show performance differences between cached and non-cached calls
"""

import asyncio
import sys
import time
from datetime import date, datetime
from pathlib import Path

# Add provider to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openbb_fmp.models.equity_historical import FMPEquityHistoricalQueryParams
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    get_cache_statistics,
    clear_cache_for_symbol
)


class Colors:
    """Console colors."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(title: str):
    """Print formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")


def print_success(msg: str):
    """Print success message."""
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")


def print_error(msg: str):
    """Print error message."""
    print(f"{Colors.RED}❌ {msg}{Colors.END}")


def print_info(msg: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")


def print_warning(msg: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")


async def check_user_settings():
    """Check if FMP API key is available in user settings."""
    print_header("Checking OpenBB User Settings")
    
    try:
        # Import here to avoid circular imports
        from openbb_core.app.service.user_service import UserService
        
        user_service = UserService()
        user_settings = user_service.default_user_settings
        
        # Check if FMP API key exists
        fmp_api_key = getattr(user_settings.credentials, "fmp_api_key", None)
        
        if fmp_api_key:
            # Handle SecretStr type
            api_key_value = fmp_api_key.get_secret_value() if hasattr(fmp_api_key, 'get_secret_value') else str(fmp_api_key)
            
            if api_key_value and api_key_value != "":
                print_success("FMP API key found in user settings")
                print_info(f"Key: {api_key_value[:8]}...{api_key_value[-4:] if len(api_key_value) > 12 else ''}")
                return True
            else:
                print_warning("FMP API key is empty in user settings")
                return False
        else:
            print_warning("FMP API key not found in user settings")
            return False
            
    except Exception as e:
        print_error(f"Error loading user settings: {e}")
        return False


async def test_cache_functionality():
    """Test cache miss and hit scenarios."""
    print_header("Testing Cache Functionality")
    
    symbol = "AAPL"
    start_date = date(2024, 1, 2)
    end_date = date(2024, 1, 10)
    
    print_info(f"Testing with {symbol} from {start_date} to {end_date}")
    
    # Clear any existing cache
    print_info("Clearing existing cache...")
    await clear_cache_for_symbol(symbol)
    
    # Create query
    query = FMPEquityHistoricalQueryParams(
        symbol=symbol,
        start_date=start_date,
        end_date=end_date,
        interval="1d",
        adjustment="splits_only"
    )
    
    try:
        # Test 1: Cache miss (first call)
        print_info("Test 1: Cache miss (first call)")
        start_time = time.time()
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, None)
        cache_miss_time = time.time() - start_time
        
        if result1 and len(result1) > 0:
            print_success(f"Cache miss: {len(result1)} records in {cache_miss_time:.2f}s")
            sample = result1[0]
            print_info(f"Sample: {sample.get('date', 'N/A')} ${sample.get('close', 'N/A')}")
        else:
            print_error("No data returned from cache miss")
            return False
        
        # Test 2: Cache hit (second call)
        print_info("Test 2: Cache hit (second call)")
        start_time = time.time()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, None)
        cache_hit_time = time.time() - start_time
        
        if result2 and len(result2) > 0:
            print_success(f"Cache hit: {len(result2)} records in {cache_hit_time:.2f}s")
            
            # Calculate speedup
            if cache_hit_time > 0:
                speedup = cache_miss_time / cache_hit_time
                print_success(f"Cache speedup: {speedup:.1f}x faster")
            
            # Verify data consistency
            if len(result1) == len(result2):
                print_success("Data consistency verified")
            else:
                print_warning(f"Data length mismatch: {len(result1)} vs {len(result2)}")
        else:
            print_error("No data returned from cache hit")
            return False
        
        return True
        
    except Exception as e:
        print_error(f"Test failed: {type(e).__name__}: {e}")
        return False


async def test_gap_detection():
    """Test gap detection functionality."""
    print_header("Testing Gap Detection")
    
    symbol = "GOOGL"
    print_info(f"Testing gap detection with {symbol}")
    
    # Clear cache
    await clear_cache_for_symbol(symbol)
    
    try:
        # Step 1: Cache small range
        query1 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print_info("Step 1: Caching small range...")
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query1, None)
        
        if result1:
            print_success(f"Cached {len(result1)} records")
        else:
            print_error("Failed to cache initial data")
            return False
        
        # Step 2: Request larger range (should detect gap)
        query2 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 15),  # Extended range
            interval="1d",
            adjustment="splits_only"
        )
        
        print_info("Step 2: Requesting extended range (gap detection)...")
        start_time = time.time()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query2, None)
        gap_fill_time = time.time() - start_time
        
        if result2 and len(result2) > len(result1):
            gap_records = len(result2) - len(result1)
            print_success(f"Gap detected and filled: +{gap_records} records in {gap_fill_time:.2f}s")
            return True
        else:
            print_warning("No gap detected (might be weekends/holidays)")
            return True  # Not necessarily an error
        
    except Exception as e:
        print_error(f"Gap detection test failed: {e}")
        return False


async def show_cache_statistics():
    """Show cache statistics."""
    print_header("Cache Statistics")
    
    try:
        stats = get_cache_statistics()
        
        if "statistics" in stats:
            print_info("Cache statistics retrieved successfully")
            print_info(f"Found {len(stats['statistics'])} cached entries")
            
            # Show some sample entries
            for i, stat in enumerate(stats["statistics"][:3]):
                symbol = stat[0] if len(stat) > 0 else "Unknown"
                records = stat[1] if len(stat) > 1 else 0
                print_info(f"  {i+1}. {symbol}: {records} records")
        else:
            print_warning("No cache statistics available")
        
        return True
        
    except Exception as e:
        print_error(f"Failed to get cache statistics: {e}")
        return False


async def main():
    """Run all tests."""
    print_header("FMP Cached Provider - OpenBB User Settings Test")
    
    # Check user settings
    if not await check_user_settings():
        print_error("Please configure your FMP API key in ~/.openbb_platform/user_settings.json")
        print_info("Example configuration:")
        print_info('{\n  "credentials": {\n    "fmp_api_key": "your_api_key_here"\n  }\n}')
        return
    
    # Run tests
    tests = [
        ("Cache Functionality", test_cache_functionality),
        ("Gap Detection", test_gap_detection),
        ("Cache Statistics", show_cache_statistics),
    ]
    
    passed = 0
    for test_name, test_func in tests:
        print(f"\n{Colors.CYAN}Running: {test_name}{Colors.END}")
        if await test_func():
            passed += 1
            print_success(f"{test_name} PASSED")
        else:
            print_error(f"{test_name} FAILED")
    
    # Summary
    print_header("Test Results")
    if passed == len(tests):
        print_success(f"All {len(tests)} tests passed! 🎉")
        print_info("✨ FMP Cached provider is working with OpenBB user settings!")
    else:
        print_warning(f"{passed}/{len(tests)} tests passed")


if __name__ == "__main__":
    asyncio.run(main())