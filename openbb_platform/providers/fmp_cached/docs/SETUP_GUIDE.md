# FMP Cached Provider Setup Guide

## 🎯 Overview
This guide will help you set up the FMP Cached Provider with MySQL database integration using OpenBB user settings.

## 📋 Prerequisites

1. **MySQL Server**: Make sure MySQL is installed and running
2. **FMP API Key**: You need a valid FMP API key
3. **OpenBB Platform**: OpenBB Platform should be installed

## 🚀 Step-by-Step Setup

### Step 1: Configure MySQL Credentials in OpenBB

Run the MySQL configuration script to add credentials to OpenBB user settings:

```bash
python configure_mysql.py
```

This will add the following to your OpenBB user settings (`~/.openbb_platform/user_settings.json`):
- `mysql_host`: localhost
- `mysql_port`: 3306  
- `mysql_user`: fmp_user
- `mysql_password`: fmp_password
- `mysql_database`: openbb_fmp_cache

### Step 2: Verify Configuration

Test that the configuration is properly set:

```bash
python -c "
import sys
sys.path.append('.')
from test_fmp_cached import test_configuration
test_configuration()
"
```

### Step 3: Set Up MySQL Database (Manual)

If you have MySQL installed and running, you can manually create the database and user:

```sql
-- Connect to MySQL as root
mysql -u root -p

-- Create database
CREATE DATABASE IF NOT EXISTS openbb_fmp_cache;

-- Create user
CREATE USER IF NOT EXISTS 'fmp_user'@'localhost' IDENTIFIED BY 'fmp_password';

-- Grant privileges
GRANT ALL PRIVILEGES ON openbb_fmp_cache.* TO 'fmp_user'@'localhost';
FLUSH PRIVILEGES;

-- Exit MySQL
EXIT;
```

### Step 4: Create Cache Tables

After the database and user are created, initialize the cache tables:

```bash
python -c "
import asyncio
import sys
sys.path.append('.')

async def setup():
    from openbb_fmp_cached.utils.database import init_database
    from openbb_fmp_cached.utils.cache_schema import create_all_tables
    
    print('Initializing database...')
    await init_database()
    
    print('Creating cache tables...')
    await create_all_tables()
    
    print('✅ Setup complete!')

asyncio.run(setup())
"
```

### Step 5: Test the Provider

Run the comprehensive test suite:

```bash
python test_fmp_cached.py
```

## 🔧 Alternative Setup (Docker MySQL)

If you don't have MySQL installed, you can use Docker:

```bash
# Start MySQL container
docker run --name mysql-fmp \
  -e MYSQL_ROOT_PASSWORD=rootpassword \
  -e MYSQL_DATABASE=openbb_fmp_cache \
  -e MYSQL_USER=fmp_user \
  -e MYSQL_PASSWORD=fmp_password \
  -p 3306:3306 \
  -d mysql:8.0

# Wait for MySQL to start
sleep 10

# Create cache tables
python -c "
import asyncio
import sys
sys.path.append('.')

async def setup():
    from openbb_fmp_cached.utils.database import init_database
    from openbb_fmp_cached.utils.cache_schema import create_all_tables
    await init_database()
    await create_all_tables()
    print('✅ Cache tables created!')

asyncio.run(setup())
"
```

## 📖 Usage Examples

### Basic Usage

```python
from openbb import obb

# Use cached provider
result = obb.equity.price.historical("AAPL", provider="fmp_cached")
df = result.to_dataframe()
print(df.head())
```

### Check Cache Performance

```python
from openbb_fmp_cached.utils.cache_manager import get_cache_manager

# Get cache statistics
cache_manager = get_cache_manager()
stats = cache_manager.get_stats()
print("Cache Stats:", stats)
```

## 🔍 Troubleshooting

### Configuration Issues
- **Missing MySQL config**: Run `configure_mysql.py`
- **Wrong credentials**: Edit `~/.openbb_platform/user_settings.json` manually

### Database Connection Issues
- **MySQL not running**: `sudo systemctl start mysql`
- **Access denied**: Check MySQL user permissions
- **Database doesn't exist**: Run the manual SQL commands above

### Cache Issues
- **Tables don't exist**: Run the cache table creation script
- **Permission denied**: Check MySQL user has proper privileges

### Test Failures
- **Provider import fails**: Make sure the provider is installed: `pip install -e .`
- **OpenBB integration fails**: The provider might not be registered with OpenBB yet

## 📊 Cache Tables

The provider creates 6 specialized cache tables:

1. `equity_historical_cache` - Historical price data
2. `equity_fundamentals_cache` - Financial statements  
3. `equity_quotes_cache` - Real-time quotes
4. `company_info_cache` - Company profiles
5. `market_data_cache` - Market indices & rates
6. `calendar_events_cache` - Earnings & events

## ⚙️ Configuration Priority

The provider loads configuration in this order:
1. **OpenBB user settings** (preferred)
2. **Environment variables** (fallback)
3. **Default values** (last resort)

## 🎉 Success Indicators

You'll know everything is working when:
- ✅ Configuration test passes
- ✅ Database connection succeeds  
- ✅ Cache operations work
- ✅ Provider imports successfully
- ✅ All 69 endpoints are available

## 📝 Files Overview

- `configure_mysql.py` - Sets up MySQL credentials in OpenBB settings
- `setup_database.py` - Creates database and user (needs MySQL root)
- `check_mysql.py` - Checks MySQL environment status
- `test_fmp_cached.py` - Comprehensive test suite
- `openbb_fmp_cached/utils/database.py` - Database configuration and connections
- `openbb_fmp_cached/utils/cache_schema.py` - Cache table definitions
- `openbb_fmp_cached/utils/cache_manager.py` - Cache operations