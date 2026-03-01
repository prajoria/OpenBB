# Migration System Documentation

## Overview
Complete cross-database migration system for transferring data from `fmp_cache.historical_prices_daily` to `openbb_fmp_cache.equity_screener`.

## Files Created

### 1. data_migration_tool.py
**Purpose**: Main migration engine with comprehensive features
- **Class**: `DataMigrator` - handles complete migration pipeline
- **Features**: 
  - Column mapping between different schemas
  - Batch processing (configurable size)
  - Dry-run mode for testing
  - Error handling and rollback
  - Progress tracking and logging
  - CLI interface with extensive options

**Key Capabilities**:
- Maps 11 common columns between schemas
- Handles 43 target-specific fields with defaults
- Stores additional data in JSON format
- Supports date range and symbol filtering
- Batch processing for performance

### 2. test_migration.py
**Purpose**: Testing framework for migration validation
- Tests database connections
- Validates transformation logic
- Performs sample migrations
- Reports success/failure statistics

**Latest Test Results**:
✅ Successfully processed 50 records in dry-run mode
✅ Migration speed: 2,583 records/second
✅ Schema transformation working correctly
✅ All validations passed

### 3. migration_scenarios.py
**Purpose**: Ready-to-use migration execution scripts
- **Scenario 1**: Dry run sample (100 records, safe testing)
- **Scenario 2**: Recent data (last 30 days)
- **Scenario 3**: Specific symbols migration
- **Scenario 4**: Incremental migration (limited records)
- **Scenario 5**: Full migration (all 1.18M records)

### 4. migration_monitor.py
**Purpose**: Migration status monitoring and validation
- Progress tracking and reporting
- Data integrity validation
- Source vs target statistics
- Recommendations based on progress

### 5. Additional Analysis Files
- `cross_database_comparison.py`: Comprehensive table analysis
- `direct_schema_comparison.py`: Schema comparison utility

## Database Schema Analysis

### Source: fmp_cache.historical_prices_daily
- **Records**: 1,184,175
- **Columns**: 16
- **Purpose**: Historical price data storage
- **Key fields**: symbol, date, open, high, low, close, volume

### Target: openbb_fmp_cache.equity_screener  
- **Records**: 92 (pre-migration)
- **Columns**: 54
- **Purpose**: Comprehensive equity screening data
- **Schema overlap**: 18.6% (11 common columns)

## Migration Column Mapping

### Direct Mappings (11 fields):
- symbol → symbol
- close → price
- date → updated_at
- volume → volume
- market_cap → market_cap
- And 6 additional mappings

### Target-Specific Fields (43 fields):
- Financial ratios, valuation metrics
- Company fundamentals
- Market data fields
- All set to NULL with migration metadata in additional_fields

## Usage Instructions

### Quick Start (Recommended):
```bash
# 1. Test migration (safe)
python migration_scenarios.py
# Select option 1 (Dry Run Sample)

# 2. Check status
python migration_monitor.py

# 3. Run actual migration
python data_migration_tool.py --max-records 1000 --batch-size 100
```

### Advanced Usage:
```bash
# Migrate recent data
python data_migration_tool.py --start-date 2024-01-01 --end-date 2024-12-31

# Migrate specific symbols
python data_migration_tool.py --symbols "AAPL TSLA MSFT" --batch-size 1000

# Full migration (all data)
python data_migration_tool.py --batch-size 5000

# Dry run with custom parameters
python data_migration_tool.py --dry-run --max-records 500 --batch-size 50
```

### CLI Options:
- `--dry-run`: Test mode (no actual changes)
- `--max-records`: Limit number of records
- `--batch-size`: Records per batch (default: 1000)
- `--start-date`: Filter by start date
- `--end-date`: Filter by end date  
- `--symbols`: Space-separated symbol list
- `--create-backup`: Backup target table before migration

## Migration Metadata

Each migrated record includes metadata in `additional_fields` JSON:
```json
{
  "migration_source": "historical_prices_daily",
  "migration_timestamp": "2024-01-15T10:30:00",
  "original_date": "2023-12-01",
  "open": 150.25,
  "high": 152.10,
  "low": 149.80,
  "close": 151.50,
  "volume": 1000000
}
```

## Performance Characteristics

- **Test Speed**: 2,583 records/second
- **Batch Processing**: Configurable (default 1000)
- **Memory Usage**: Optimized with batch processing
- **Error Handling**: Comprehensive with rollback capability

## Data Integrity

The system validates:
- Schema transformation accuracy
- Data type conversions
- Null value handling
- JSON field storage
- Migration metadata consistency

## Safety Features

1. **Dry-run Mode**: Test without changes
2. **Backup Creation**: Automatic target backup
3. **Rollback Capability**: Undo failed migrations  
4. **Progress Tracking**: Detailed logging
5. **Error Handling**: Graceful failure management
6. **Batch Processing**: Prevents memory issues

## Recommendations

### For Production Use:
1. Always test with dry-run first
2. Start with small record counts
3. Monitor progress regularly
4. Validate data integrity
5. Create backups before large migrations

### Migration Strategy:
1. **Phase 1**: Dry-run testing (Scenario 1)
2. **Phase 2**: Recent data migration (Scenario 2)
3. **Phase 3**: Incremental migration (Scenario 4)
4. **Phase 4**: Full migration if needed (Scenario 5)

## Database Configuration

Update database credentials in each script:
```python
source_config = {
    'host': 'your_host',
    'user': 'your_user', 
    'password': 'your_password',
    'database': 'fmp_cache'
}

target_config = {
    'host': 'your_host',
    'user': 'your_user',
    'password': 'your_password', 
    'database': 'openbb_fmp_cache'
}
```

## Support and Troubleshooting

- Check logs for detailed error information
- Use migration monitor for status tracking
- Test with small samples before full migration
- Validate data integrity regularly
- Contact support for complex migration issues

## Migration Summary

This comprehensive system provides everything needed for safe, efficient migration of 1.18M historical price records to the equity screener table with proper schema transformation, error handling, and validation capabilities.