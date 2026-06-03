"""Test script for flattened cache approach."""

import asyncio
from datetime import datetime, timedelta
from openbb_fmp_cached.utils.cache_manager import get_flattened_cache_manager

async def test_flattened_cache():
    """Test the flattened cache system."""
    print("🧪 Testing flattened cache system...")
    
    cache_manager = get_flattened_cache_manager()
    
    # Test data that matches equity_historical structure
    test_data = [
        {
            "symbol": "AAPL",
            "date": datetime.now().date(),
            "open": 150.25,
            "high": 155.75,
            "low": 149.50,
            "close": 154.80,
            "volume": 50000000,
            "vwap": 152.50,
            "change_amount": 4.55,
            "change_percent": 0.0304
        },
        {
            "symbol": "MSFT", 
            "date": datetime.now().date(),
            "open": 280.15,
            "high": 285.25,
            "low": 279.80,
            "close": 284.50,
            "volume": 30000000,
            "vwap": 282.40,
            "change_amount": 4.35,
            "change_percent": 0.0155
        }
    ]
    
    # Test storing data
    print("📝 Testing data storage...")
    success = await cache_manager.store_cached_data_async(
        "EquityHistorical",
        test_data,
        symbol="AAPL,MSFT",
        interval="1d"
    )
    
    if success:
        print("✅ Data stored successfully!")
    else:
        print("❌ Failed to store data")
        return
    
    # Test retrieving data
    print("📖 Testing data retrieval...")
    retrieved_data = await cache_manager.get_cached_data_async(
        "EquityHistorical",
        symbol="AAPL"
    )
    
    if retrieved_data:
        print(f"✅ Retrieved {len(retrieved_data)} records for AAPL")
        print("Sample record:", retrieved_data[0])
        
        # Test DataFrame conversion
        df = cache_manager.to_dataframe(retrieved_data)
        print(f"📊 DataFrame shape: {df.shape}")
        print(f"📊 DataFrame columns: {list(df.columns)}")
        
    else:
        print("❌ No data retrieved")
    
    # Test stats
    stats = cache_manager.get_stats()
    print("\n📈 Cache Statistics:")
    for key, value in stats.items():
        print(f"  {key}: {value}")


if __name__ == "__main__":
    asyncio.run(test_flattened_cache())