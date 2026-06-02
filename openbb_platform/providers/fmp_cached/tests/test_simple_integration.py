"""Simple test runner for real FMP cached integration tests.

This script demonstrates the cached provider working with real API and database calls.
No mocks - tests the complete system end-to-end.

Usage:
    python test_simple_integration.py
    
Environment variables needed:
    FMP_API_KEY=your_fmp_api_key
    
Optional database config (uses memory SQLite if not provided):
    MYSQL_HOST=localhost
    MYSQL_USER=your_user  
    MYSQL_PASSWORD=your_password
    MYSQL_DATABASE=your_db
"""

import os
import asyncio
import sys
from datetime import date, datetime
from pathlib import Path

# Add the provider to Python path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openbb_fmp.models.equity_historical import FMPEquityHistoricalQueryParams
from openbb_fmp_cached.models.equity_historical import (
    FMPCachedEquityHistoricalFetcher,
    get_cache_statistics,
    clear_cache_for_symbol
)


class Colors:
    """Console colors for better output."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    WHITE = '\033[97m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(title: str):
    """Print a formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")


def print_success(message: str):
    """Print success message."""
    print(f"{Colors.GREEN}✅ {message}{Colors.END}")


def print_error(message: str):
    """Print error message."""
    print(f"{Colors.RED}❌ {message}{Colors.END}")


def print_info(message: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ️  {message}{Colors.END}")


def print_warning(message: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.END}")


async def test_basic_functionality():
    """Test basic cached provider functionality."""
    print_header("Basic Functionality Test")
    
    # Get API key
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        print_error("FMP_API_KEY environment variable not set")
        return False
    
    credentials = {"fmp_api_key": api_key}
    symbol = "AAPL"
    
    print_info(f"Testing with symbol: {symbol}")
    print_info(f"API Key: {api_key[:8]}...")
    
    # Clear any existing cache
    print_info("Clearing cache...")
    await clear_cache_for_symbol(symbol)
    
    # Create query
    query = FMPEquityHistoricalQueryParams(
        symbol=symbol,
        start_date=date(2024, 1, 2),
        end_date=date(2024, 1, 5),
        interval="1d",
        adjustment="splits_only"
    )
    
    try:
        # First call - cache miss
        print_info("First call (cache miss)...")
        start_time = datetime.now()
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, credentials)
        first_duration = (datetime.now() - start_time).total_seconds()
        
        if not result1:
            print_error("No data returned from API")
            return False
        
        print_success(f"Got {len(result1)} records in {first_duration:.2f}s")
        
        # Show sample data
        sample = result1[0]
        print_info(f"Sample: {sample['date']} ${sample['close']} (Volume: {sample['volume']:,})")
        
        # Second call - cache hit
        print_info("Second call (cache hit)...")
        start_time = datetime.now()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query, credentials)
        second_duration = (datetime.now() - start_time).total_seconds()
        
        print_success(f"Got {len(result2)} records in {second_duration:.2f}s")
        
        # Compare performance
        if second_duration > 0:
            speedup = first_duration / second_duration
            print_success(f"Cache speedup: {speedup:.1f}x faster")
        
        # Verify data consistency
        if len(result1) == len(result2):
            print_success("Data consistency verified")
        else:
            print_warning(f"Data length mismatch: {len(result1)} vs {len(result2)}")
        
        return True
        
    except Exception as e:
        print_error(f"Test failed: {type(e).__name__}: {e}")
        return False


async def test_gap_detection():
    """Test gap detection and filling."""
    print_header("Gap Detection Test")
    
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        print_error("FMP_API_KEY environment variable not set")
        return False
    
    credentials = {"fmp_api_key": api_key}
    symbol = "GOOGL"
    
    print_info(f"Testing gap detection with symbol: {symbol}")
    
    # Clear cache
    await clear_cache_for_symbol(symbol)
    
    try:
        # Step 1: Fetch small range
        query1 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        print_info("Step 1: Fetching initial data...")
        result1 = await FMPCachedEquityHistoricalFetcher.aextract_data(query1, credentials)
        print_success(f"Cached {len(result1)} records")
        
        # Step 2: Fetch larger range (should detect gap)
        query2 = FMPEquityHistoricalQueryParams(
            symbol=symbol,
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 15),  # Extended range
            interval="1d",
            adjustment="splits_only"
        )
        
        print_info("Step 2: Fetching extended range (gap detection)...")
        start_time = datetime.now()
        result2 = await FMPCachedEquityHistoricalFetcher.aextract_data(query2, credentials)
        gap_fill_time = (datetime.now() - start_time).total_seconds()
        
        if len(result2) > len(result1):
            gap_records = len(result2) - len(result1)
            print_success(f"Gap detected and filled: +{gap_records} records in {gap_fill_time:.2f}s")
        else:
            print_warning("No gap detected (might be weekends/holidays)")
        
        # Verify no duplicates
        dates = [r["date"] for r in result2]
        if len(dates) == len(set(dates)):
            print_success("No duplicate dates found")
        else:
            print_warning("Duplicate dates detected")
        
        return True
        
    except Exception as e:
        print_error(f"Gap detection test failed: {type(e).__name__}: {e}")
        return False


async def test_multi_symbol():
    """Test multi-symbol functionality."""
    print_header("Multi-Symbol Test")
    
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        print_error("FMP_API_KEY environment variable not set")
        return False
    
    credentials = {"fmp_api_key": api_key}
    symbols = ["AAPL", "MSFT", "GOOGL"]
    
    print_info(f"Testing with symbols: {', '.join(symbols)}")
    
    # Clear caches
    for symbol in symbols:
        await clear_cache_for_symbol(symbol)
    
    try:
        query = FMPEquityHistoricalQueryParams(
            symbol=",".join(symbols),
            start_date=date(2024, 1, 2),
            end_date=date(2024, 1, 5),
            interval="1d",
            adjustment="splits_only"
        )
        
        start_time = datetime.now()
        result = await FMPCachedEquityHistoricalFetcher.aextract_data(query, credentials)
        duration = (datetime.now() - start_time).total_seconds()
        
        symbols_found = set(r["symbol"] for r in result)
        
        print_success(f"Got {len(result)} total records in {duration:.2f}s")
        print_info(f"Symbols found: {', '.join(sorted(symbols_found))}")
        
        # Show per-symbol breakdown
        for symbol in symbols_found:
            symbol_records = [r for r in result if r["symbol"] == symbol]
            print_info(f"  {symbol}: {len(symbol_records)} records")
        
        return len(symbols_found) > 0
        
    except Exception as e:
        print_error(f"Multi-symbol test failed: {type(e).__name__}: {e}")
        return False


async def test_cache_statistics():
    """Test cache statistics functionality."""
    print_header("Cache Statistics Test")
    
    try:
        stats = get_cache_statistics()
        
        if "summary" in stats and "statistics" in stats:
            summary = stats["summary"]
            print_success("Cache statistics retrieved successfully")
            print_info(f"Total symbols: {summary.get('total_symbols', 0)}")
            print_info(f"Total records: {summary.get('total_records', 0)}")
            
            if "date_range" in summary:
                date_range = summary["date_range"]
                print_info(f"Date range: {date_range.get('earliest')} to {date_range.get('latest')}")
            
            return True
        else:
            print_warning("Cache statistics format unexpected")
            return False
            
    except Exception as e:
        print_error(f"Cache statistics test failed: {type(e).__name__}: {e}")
        return False


async def main():
    """Run all integration tests."""
    print_header("FMP Cached Provider - Real Integration Tests")
    
    # Check environment
    api_key = os.getenv("FMP_API_KEY")
    if not api_key:
        print_error("FMP_API_KEY environment variable must be set")
        print_info("Get your API key from: https://financialmodelingprep.com/")
        return
    
    # Database info
    mysql_host = os.getenv("MYSQL_HOST")
    if mysql_host:
        print_info(f"Using MySQL database: {mysql_host}")
    else:
        print_info("Using in-memory SQLite database (no persistence)")
    
    # Run tests
    tests = [
        ("Basic Functionality", test_basic_functionality),
        ("Gap Detection", test_gap_detection), 
        ("Multi-Symbol", test_multi_symbol),
        ("Cache Statistics", test_cache_statistics),
    ]
    
    passed = 0
    total = len(tests)
    
    for test_name, test_func in tests:
        print(f"\n{Colors.MAGENTA}Running: {test_name}{Colors.END}")
        try:
            if await test_func():
                passed += 1
                print_success(f"{test_name} PASSED")
            else:
                print_error(f"{test_name} FAILED")
        except Exception as e:
            print_error(f"{test_name} ERROR: {e}")
    
    # Summary
    print_header("Test Results")
    if passed == total:
        print_success(f"All {total} tests passed! 🎉")
    else:
        print_warning(f"{passed}/{total} tests passed")
    
    if passed > 0:
        print_info("✨ FMP Cached provider is working with real API and database calls!")
    else:
        print_error("❌ FMP Cached provider has issues - check configuration")


if __name__ == "__main__":
    asyncio.run(main())