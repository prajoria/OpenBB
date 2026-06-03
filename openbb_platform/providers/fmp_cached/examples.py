#!/usr/bin/env python3
"""Example usage of FMP Cached provider."""

import asyncio
from datetime import datetime, timedelta
from openbb import obb

def example_basic_usage():
    """Basic usage example."""
    print("📈 Basic Usage Example")
    print("-" * 30)
    
    # Get historical data for AAPL (will be cached for future requests)
    print("Fetching AAPL historical data...")
    result = obb.equity.price.historical(
        "AAPL",
        start_date=datetime.now() - timedelta(days=30),
        end_date=datetime.now() - timedelta(days=1),
        provider="fmp_cached"
    )
    
    df = result.to_df()
    print(f"Got {len(df)} rows of data")
    print(df.head())
    
    # Second call should be faster (cached)
    print("\nSecond call (should be faster - cached)...")
    start_time = datetime.now()
    result2 = obb.equity.price.historical(
        "AAPL",
        start_date=datetime.now() - timedelta(days=30),
        end_date=datetime.now() - timedelta(days=1),
        provider="fmp_cached"
    )
    elapsed = (datetime.now() - start_time).total_seconds()
    print(f"Second call took {elapsed:.3f} seconds")

def example_fundamentals():
    """Fundamentals data example."""
    print("\n📊 Fundamentals Example")
    print("-" * 30)
    
    # Get balance sheet data (cached for 24 hours)
    print("Fetching AAPL balance sheet...")
    balance_sheet = obb.equity.fundamental.balance(
        "AAPL",
        provider="fmp_cached"
    )
    
    df = balance_sheet.to_df()
    print(f"Got {len(df)} periods of balance sheet data")
    print(df.columns.tolist())

def example_quotes():
    """Real-time quotes example."""
    print("\n💰 Real-time Quotes Example")  
    print("-" * 30)
    
    # Get real-time quote (cached for 1 minute)
    print("Fetching AAPL quote...")
    quote = obb.equity.price.quote("AAPL", provider="fmp_cached")
    
    data = quote.to_df()
    print("Current quote data:")
    print(data[['symbol', 'price', 'change', 'change_percent']].to_string())

def example_multiple_symbols():
    """Multiple symbols example."""
    print("\n📋 Multiple Symbols Example")
    print("-" * 30)
    
    symbols = ["AAPL", "GOOGL", "MSFT"]
    
    for symbol in symbols:
        print(f"Fetching data for {symbol}...")
        result = obb.equity.price.historical(
            symbol,
            start_date=datetime.now() - timedelta(days=7),
            provider="fmp_cached"
        )
        df = result.to_df()
        latest_price = df.iloc[-1]['close'] if not df.empty else "N/A"
        print(f"  Latest close: ${latest_price}")

async def example_cache_statistics():
    """Show cache statistics."""
    print("\n📊 Cache Statistics")
    print("-" * 30)
    
    try:
        from openbb_fmp_cached.utils.cache_manager import get_cache_manager
        
        cache_manager = get_cache_manager()
        stats = cache_manager.get_stats()
        
        print("Cache Performance:")
        for key, value in stats.items():
            print(f"  {key}: {value}")
            
        # Show cache hit rate
        if stats['total_requests'] > 0:
            hit_rate = stats['hit_rate_percent']
            print(f"\nCache efficiency: {hit_rate}% hit rate")
            
            if hit_rate > 50:
                print("✅ Good cache performance!")
            else:
                print("⚠️ Consider adjusting cache TTL settings")
        
    except Exception as e:
        print(f"Could not retrieve cache statistics: {e}")

async def example_cache_management():
    """Cache management example."""
    print("\n🔧 Cache Management")
    print("-" * 30)
    
    try:
        from openbb_fmp_cached.utils.cache_manager import get_cache_manager
        from openbb_fmp_cached.utils.cache_schema import cleanup_expired_cache
        
        cache_manager = get_cache_manager()
        
        # Clean up expired cache entries
        print("Cleaning up expired cache entries...")
        deleted_count = await cleanup_expired_cache()
        print(f"Deleted {deleted_count} expired cache entries")
        
        # Invalidate cache for a specific symbol
        print("Invalidating cache for AAPL...")
        await cache_manager.invalidate_cache(pattern="AAPL")
        print("Cache invalidated")
        
    except Exception as e:
        print(f"Cache management failed: {e}")

def main():
    """Run all examples."""
    print("🚀 FMP Cached Provider Examples")
    print("=" * 50)
    
    try:
        # Basic examples
        example_basic_usage()
        example_fundamentals() 
        example_quotes()
        example_multiple_symbols()
        
        # Async examples
        asyncio.run(example_cache_statistics())
        asyncio.run(example_cache_management())
        
        print("\n🎉 All examples completed!")
        print("\nTips:")
        print("- First requests are slower (API calls)")
        print("- Subsequent requests are faster (cached)")
        print("- Cache TTL varies by data type")
        print("- Check ~/.openbb_platform/user_settings.json for config")
        
    except Exception as e:
        print(f"❌ Example failed: {e}")
        print("\nMake sure:")
        print("1. MySQL server is running")
        print("2. Database credentials are correct")
        print("3. FMP API key is valid")
        print("4. Provider is properly installed")

if __name__ == "__main__":
    main()