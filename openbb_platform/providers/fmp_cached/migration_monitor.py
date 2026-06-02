#!/usr/bin/env python3
"""
Migration Status Monitor

Monitor and track migration progress, validate results, and provide status reports.
"""

import sys
import os
import pymysql
import json
from datetime import datetime
from dataclasses import dataclass
from typing import Optional, Dict, List

# Add the provider path to import OpenBB database utils
sys.path.append(os.path.join(os.path.dirname(__file__), 'openbb_fmp_cached', 'utils'))

try:
    from openbb_fmp_cached.utils.database import DatabaseConfig
except ImportError:
    # Fallback if OpenBB database utils not available
    print("⚠️  OpenBB database configuration not found, using fallback configuration")
    DatabaseConfig = None

@dataclass
class MigrationStatus:
    """Migration status information."""
    total_source_records: int
    total_target_records: int
    migration_progress: float
    latest_migrated_date: Optional[str]
    symbols_migrated: int
    symbols_total: int
    data_integrity_ok: bool
    last_migration_time: Optional[str]

class MigrationMonitor:
    """Monitor migration progress and status."""
    
    def __init__(self):
        if DatabaseConfig:
            # Use OpenBB database configuration
            config = DatabaseConfig()
            db_config = config.config.copy()
            
            self.target_config = {
                'host': db_config['host'],
                'port': db_config['port'], 
                'user': db_config['user'],
                'password': db_config['password'],
                'database': db_config['database'],
                'charset': db_config.get('charset', 'utf8mb4')
            }
            
            # Source database - assume same connection but different database name
            self.source_config = self.target_config.copy()
            self.source_config['database'] = 'fmp_cache'
            
            print(f"✅ Using OpenBB database configuration: {db_config['host']}:{db_config['port']}")
        else:
            # Fallback to environment variables or defaults
            self.source_config = {
                'host': os.getenv('DB_HOST', 'localhost'),
                'port': int(os.getenv('DB_PORT', 3306)),
                'user': os.getenv('DB_USER', 'fmp_user'),
                'password': os.getenv('DB_PASSWORD', 'fmp_password'),
                'database': 'fmp_cache',
                'charset': 'utf8mb4'
            }
            
            self.target_config = self.source_config.copy()
            self.target_config['database'] = 'openbb_fmp_cache'
            
            print(f"⚠️  Using fallback configuration: {self.source_config['host']}:{self.source_config['port']}")
    
    def get_database_connection(self, config: dict):
        """Get database connection."""
        return pymysql.connect(**config)
    
    def get_source_stats(self) -> dict:
        """Get source database statistics."""
        with self.get_database_connection(self.source_config) as conn:
            with conn.cursor() as cursor:
                # Total records
                cursor.execute("SELECT COUNT(*) FROM historical_prices_daily")
                total_records = cursor.fetchone()[0]
                
                # Date range
                cursor.execute("SELECT MIN(date), MAX(date) FROM historical_prices_daily")
                min_date, max_date = cursor.fetchone()
                
                # Unique symbols
                cursor.execute("SELECT COUNT(DISTINCT symbol) FROM historical_prices_daily")
                unique_symbols = cursor.fetchone()[0]
                
                # Sample of latest data
                cursor.execute("""
                    SELECT symbol, date, close 
                    FROM historical_prices_daily 
                    ORDER BY date DESC 
                    LIMIT 5
                """)
                latest_samples = cursor.fetchall()
                
                return {
                    'total_records': total_records,
                    'date_range': f"{min_date} to {max_date}",
                    'unique_symbols': unique_symbols,
                    'latest_samples': latest_samples
                }
    
    def get_target_stats(self) -> dict:
        """Get target database statistics."""
        with self.get_database_connection(self.target_config) as conn:
            with conn.cursor() as cursor:
                # Check if table exists
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM information_schema.tables 
                    WHERE table_schema = 'openbb_fmp_cache' 
                    AND table_name = 'equity_screener'
                """)
                
                if cursor.fetchone()[0] == 0:
                    return {
                        'table_exists': False,
                        'total_records': 0,
                        'unique_symbols': 0,
                        'latest_samples': []
                    }
                
                # Total records
                cursor.execute("SELECT COUNT(*) FROM equity_screener")
                total_records = cursor.fetchone()[0]
                
                # Records with migration metadata
                cursor.execute("""
                    SELECT COUNT(*) 
                    FROM equity_screener 
                    WHERE additional_fields IS NOT NULL 
                    AND JSON_EXTRACT(additional_fields, '$.migration_source') = 'historical_prices_daily'
                """)
                migrated_records = cursor.fetchone()[0]
                
                # Unique symbols from migrated data
                cursor.execute("""
                    SELECT COUNT(DISTINCT symbol) 
                    FROM equity_screener 
                    WHERE additional_fields IS NOT NULL 
                    AND JSON_EXTRACT(additional_fields, '$.migration_source') = 'historical_prices_daily'
                """)
                migrated_symbols = cursor.fetchone()[0]
                
                # Date range of migrated data
                cursor.execute("""
                    SELECT 
                        MIN(JSON_EXTRACT(additional_fields, '$.original_date')),
                        MAX(JSON_EXTRACT(additional_fields, '$.original_date'))
                    FROM equity_screener 
                    WHERE additional_fields IS NOT NULL 
                    AND JSON_EXTRACT(additional_fields, '$.migration_source') = 'historical_prices_daily'
                """)
                date_range = cursor.fetchone()
                
                # Latest migrated samples
                cursor.execute("""
                    SELECT 
                        symbol, 
                        price,
                        JSON_EXTRACT(additional_fields, '$.original_date') as original_date,
                        JSON_EXTRACT(additional_fields, '$.migration_timestamp') as migration_time
                    FROM equity_screener 
                    WHERE additional_fields IS NOT NULL 
                    AND JSON_EXTRACT(additional_fields, '$.migration_source') = 'historical_prices_daily'
                    ORDER BY JSON_EXTRACT(additional_fields, '$.migration_timestamp') DESC
                    LIMIT 5
                """)
                latest_samples = cursor.fetchall()
                
                return {
                    'table_exists': True,
                    'total_records': total_records,
                    'migrated_records': migrated_records,
                    'migrated_symbols': migrated_symbols,
                    'date_range': date_range,
                    'latest_samples': latest_samples
                }
    
    def validate_data_integrity(self) -> dict:
        """Validate data integrity between source and target."""
        try:
            # Sample validation - compare a few records
            with self.get_database_connection(self.source_config) as source_conn:
                with source_conn.cursor() as source_cursor:
                    source_cursor.execute("""
                        SELECT symbol, date, open, high, low, close, volume 
                        FROM historical_prices_daily 
                        ORDER BY RAND() 
                        LIMIT 10
                    """)
                    source_samples = source_cursor.fetchall()
            
            integrity_results = []
            
            with self.get_database_connection(self.target_config) as target_conn:
                with target_conn.cursor() as target_cursor:
                    for sample in source_samples:
                        symbol, date, open_p, high, low, close, volume = sample
                        
                        # Find corresponding record in target
                        target_cursor.execute("""
                            SELECT 
                                symbol, price,
                                JSON_EXTRACT(additional_fields, '$.original_date'),
                                JSON_EXTRACT(additional_fields, '$.open'),
                                JSON_EXTRACT(additional_fields, '$.high'),
                                JSON_EXTRACT(additional_fields, '$.low'),
                                JSON_EXTRACT(additional_fields, '$.close'),
                                JSON_EXTRACT(additional_fields, '$.volume')
                            FROM equity_screener 
                            WHERE symbol = %s 
                            AND JSON_EXTRACT(additional_fields, '$.original_date') = %s
                            AND JSON_EXTRACT(additional_fields, '$.migration_source') = 'historical_prices_daily'
                        """, (symbol, str(date)))
                        
                        target_record = target_cursor.fetchone()
                        
                        if target_record:
                            # Compare values
                            _, target_price, _, target_open, target_high, target_low, target_close, target_volume = target_record
                            
                            matches = {
                                'symbol': symbol,
                                'date': str(date),
                                'close_match': abs(float(close) - float(target_close)) < 0.01 if target_close else False,
                                'volume_match': int(volume or 0) == int(target_volume or 0),
                                'found': True
                            }
                        else:
                            matches = {
                                'symbol': symbol,
                                'date': str(date),
                                'close_match': False,
                                'volume_match': False,
                                'found': False
                            }
                        
                        integrity_results.append(matches)
            
            # Calculate integrity score
            total_checks = len(integrity_results)
            found_records = sum(1 for r in integrity_results if r['found'])
            close_matches = sum(1 for r in integrity_results if r['close_match'])
            
            integrity_score = (found_records + close_matches) / (total_checks * 2) if total_checks > 0 else 0
            
            return {
                'integrity_score': integrity_score,
                'total_checks': total_checks,
                'found_records': found_records,
                'close_matches': close_matches,
                'details': integrity_results
            }
            
        except Exception as e:
            return {
                'integrity_score': 0,
                'error': str(e),
                'total_checks': 0,
                'found_records': 0,
                'close_matches': 0,
                'details': []
            }
    
    def get_migration_status(self) -> MigrationStatus:
        """Get comprehensive migration status."""
        try:
            source_stats = self.get_source_stats()
            target_stats = self.get_target_stats()
            integrity = self.validate_data_integrity()
            
            if not target_stats['table_exists']:
                progress = 0.0
                migrated_records = 0
                migrated_symbols = 0
                latest_date = None
                last_migration = None
            else:
                migrated_records = target_stats.get('migrated_records', 0)
                migrated_symbols = target_stats.get('migrated_symbols', 0)
                progress = (migrated_records / source_stats['total_records']) * 100 if source_stats['total_records'] > 0 else 0
                
                # Extract latest date and migration time
                if target_stats['latest_samples']:
                    latest_sample = target_stats['latest_samples'][0]
                    latest_date = latest_sample[2] if len(latest_sample) > 2 else None
                    last_migration = latest_sample[3] if len(latest_sample) > 3 else None
                    if latest_date:
                        latest_date = str(latest_date).strip('"')
                    if last_migration:
                        last_migration = str(last_migration).strip('"')
                else:
                    latest_date = None
                    last_migration = None
            
            return MigrationStatus(
                total_source_records=source_stats['total_records'],
                total_target_records=migrated_records,
                migration_progress=progress,
                latest_migrated_date=latest_date,
                symbols_migrated=migrated_symbols,
                symbols_total=source_stats['unique_symbols'],
                data_integrity_ok=integrity['integrity_score'] > 0.8,
                last_migration_time=last_migration
            )
            
        except Exception as e:
            print(f"Error getting migration status: {e}")
            return MigrationStatus(
                total_source_records=0,
                total_target_records=0,
                migration_progress=0.0,
                latest_migrated_date=None,
                symbols_migrated=0,
                symbols_total=0,
                data_integrity_ok=False,
                last_migration_time=None
            )
    
    def print_status_report(self):
        """Print comprehensive status report."""
        print("🔍 MIGRATION STATUS REPORT")
        print("=" * 60)
        
        try:
            source_stats = self.get_source_stats()
            target_stats = self.get_target_stats()
            integrity = self.validate_data_integrity()
            status = self.get_migration_status()
            
            print("📊 SOURCE DATABASE (fmp_cache.historical_prices_daily)")
            print("-" * 40)
            print(f"Total records: {source_stats['total_records']:,}")
            print(f"Date range: {source_stats['date_range']}")
            print(f"Unique symbols: {source_stats['unique_symbols']:,}")
            
            print(f"\\n📈 TARGET DATABASE (openbb_fmp_cache.equity_screener)")
            print("-" * 40)
            if target_stats['table_exists']:
                print(f"Total records: {target_stats['total_records']:,}")
                print(f"Migrated records: {target_stats.get('migrated_records', 0):,}")
                print(f"Migrated symbols: {target_stats.get('migrated_symbols', 0):,}")
                if target_stats['date_range'][0]:
                    print(f"Migrated date range: {target_stats['date_range'][0]} to {target_stats['date_range'][1]}")
            else:
                print("❌ Table does not exist")
            
            print(f"\\n📈 MIGRATION PROGRESS")
            print("-" * 40)
            print(f"Progress: {status.migration_progress:.2f}%")
            print(f"Records migrated: {status.total_target_records:,} / {status.total_source_records:,}")
            print(f"Symbols migrated: {status.symbols_migrated:,} / {status.symbols_total:,}")
            if status.latest_migrated_date:
                print(f"Latest migrated date: {status.latest_migrated_date}")
            if status.last_migration_time:
                print(f"Last migration: {status.last_migration_time}")
            
            print(f"\\n🔍 DATA INTEGRITY")
            print("-" * 40)
            print(f"Integrity score: {integrity['integrity_score']:.1%}")
            print(f"Sample checks: {integrity['total_checks']}")
            print(f"Records found: {integrity['found_records']}/{integrity['total_checks']}")
            print(f"Value matches: {integrity['close_matches']}/{integrity['total_checks']}")
            print(f"Status: {'✅ GOOD' if status.data_integrity_ok else '❌ ISSUES'}")
            
            if target_stats['table_exists'] and target_stats.get('latest_samples'):
                print(f"\\n📝 RECENT MIGRATIONS")
                print("-" * 40)
                for sample in target_stats['latest_samples'][:3]:
                    symbol = sample[0]
                    price = sample[1]
                    date = str(sample[2]).strip('"') if sample[2] else 'N/A'
                    migration_time = str(sample[3]).strip('"') if sample[3] else 'N/A'
                    print(f"{symbol}: ${price} (Date: {date}, Migrated: {migration_time[:19]})")
            
            # Progress bar
            print(f"\\n📊 PROGRESS BAR")
            print("-" * 40)
            bar_length = 40
            filled_length = int(bar_length * status.migration_progress / 100)
            bar = '█' * filled_length + '░' * (bar_length - filled_length)
            print(f"[{bar}] {status.migration_progress:.1f}%")
            
            # Recommendations
            print(f"\\n💡 RECOMMENDATIONS")
            print("-" * 40)
            
            if status.migration_progress == 0:
                print("• Run a test migration to begin data transfer")
                print("• Start with: python migration_scenarios.py → Option 1 (Dry Run)")
            elif status.migration_progress < 10:
                print("• Migration just started - monitor for errors")
                print("• Consider incremental migration for better control")
            elif status.migration_progress < 50:
                print("• Migration in progress - good time to validate results")
                print("• Check data integrity regularly")
            elif status.migration_progress < 90:
                print("• Migration progressing well")
                print("• Prepare for completion validation")
            else:
                print("• Migration nearly complete!")
                print("• Perform final data validation")
                print("• Consider backup of target database")
            
            if not status.data_integrity_ok:
                print("⚠️  • Data integrity issues detected - investigate immediately")
            
        except Exception as e:
            print(f"❌ Error generating status report: {e}")
        
        print("=" * 60)


def main():
    """Main function."""
    monitor = MigrationMonitor()
    monitor.print_status_report()


if __name__ == "__main__":
    main()