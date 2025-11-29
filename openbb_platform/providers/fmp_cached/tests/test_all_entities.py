"""
Comprehensive test for all 67 FMP cached entities.
Tests database population without mocking for all entity endpoints.
"""

import asyncio
import os
import sys
from typing import Dict, Any, List, Optional
import pandas as pd
from datetime import datetime, date
import traceback

# Add the provider to the path
sys.path.append('/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached')

from openbb_fmp_cached.utils.database import execute_query
from openbb_fmp_cached.utils.cache_manager import get_database_manager
from openbb_fmp_cached.utils.cache_schema import FLATTENED_TABLES


class EntityTester:
    """Test all entities for database population."""
    
    def __init__(self):
        self.db_manager = get_database_manager()
        self.test_results = {}
        self.successful_tests = 0
        self.failed_tests = 0
        
    def log(self, message: str, level: str = "INFO"):
        """Log test message with timestamp."""
        timestamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{timestamp}] {level}: {message}")
        
    def create_sample_data(self, entity_name: str) -> Dict[str, Any]:
        """Create realistic sample data for an entity."""
        base_data = {
            'symbol': 'AAPL',
            'date': date(2024, 1, 15),
            'period': 'annual',
            'currency': 'USD',
            'exchange': 'NASDAQ',
        }
        
        # Add financial data based on entity type
        if 'historical' in entity_name or 'quote' in entity_name:
            base_data.update({
                'open': 150.25,
                'high': 155.80,
                'low': 148.90,
                'close': 154.33,
                'volume': 45678901,
                'vwap': 152.15,
                'change': 3.75,  # This will be mapped to change_amount
                'change_percent': 2.48
            })
            
        elif 'balance_sheet' in entity_name:
            base_data.update({
                'total_assets': 365725000000,
                'total_liabilities': 258549000000,
                'total_equity': 107176000000,
                'cash_and_cash_equivalents': 29043000000,
                'total_debt': 95281000000,
                'working_capital': 9355000000
            })
            
        elif 'income_statement' in entity_name:
            base_data.update({
                'revenue': 365817000000,
                'cost_of_revenue': 214137000000,
                'gross_profit': 151680000000,
                'operating_expenses': 51345000000,
                'operating_income': 100335000000,
                'net_income': 94680000000,
                'eps': 5.89,
                'eps_diluted': 5.89
            })
            
        elif 'cash_flow' in entity_name:
            base_data.update({
                'operating_cash_flow': 104038000000,
                'investing_cash_flow': -3035000000,
                'financing_cash_flow': -110749000000,
                'free_cash_flow': 93353000000,
                'capital_expenditure': 10685000000
            })
            
        elif 'ratios' in entity_name or 'metrics' in entity_name:
            base_data.update({
                'pe_ratio': 26.21,
                'pb_ratio': 39.55,
                'debt_to_equity': 1.88,
                'current_ratio': 1.07,
                'roe': 0.617,
                'roa': 0.259
            })
            
        elif 'profile' in entity_name:
            base_data.update({
                'company_name': 'Apple Inc.',
                'sector': 'Technology',
                'industry': 'Consumer Electronics', 
                'country': 'United States',
                'market_cap': 2920000000000,
                'price': 154.33,
                'beta': 1.25,
                'description': 'Apple Inc. designs, manufactures, and markets smartphones, personal computers, tablets, wearables, and accessories worldwide.',
                'ceo': 'Timothy Cook',
                'employees': 164000,
                'website': 'https://www.apple.com'
            })
            
        elif 'screener' in entity_name:
            # Equity screener needs comprehensive data for stock screening
            base_data.update({
                # Price data
                'open': 150.25,
                'high': 155.80,
                'low': 148.90,
                'close': 154.33,
                'volume': 45678901,
                'price': 154.33,
                'change': 3.75,  # Will be mapped to change_amount
                'change_percent': 2.48,
                
                # Company info
                'company_name': 'Apple Inc.',
                'sector': 'Technology',
                'industry': 'Consumer Electronics',
                'country': 'United States',
                'market_cap': 2920000000000,
                'beta': 1.25,
                'employees': 164000,
                
                # Financial metrics
                'revenue': 365817000000,
                'net_income': 94680000000,
                'eps': 5.89,
                'eps_diluted': 5.89,
                
                # Ratios for screening
                'pe_ratio': 26.21,
                'pb_ratio': 39.55,
                'debt_to_equity': 1.88,
                'current_ratio': 1.07,
                'roe': 0.617,
                'roa': 0.259
            })
            
        # Add some additional fields that would go to additional_fields JSON
        base_data.update({
            'custom_field_1': 'test_value',
            'custom_metric': 42.5,
            'metadata_flag': True,
            'test_timestamp': datetime.now().isoformat()
        })
        
        return base_data
        
    def test_entity_storage(self, entity_name: str) -> Dict[str, Any]:
        """Test storing and retrieving data for a single entity."""
        try:
            self.log(f"Testing entity: {entity_name}")
            
            # Create sample data
            sample_data = self.create_sample_data(entity_name)
            
            # Get table name
            table_name = entity_name
            if table_name not in FLATTENED_TABLES:
                raise ValueError(f"Table {table_name} not found in FLATTENED_TABLES")
            
            # Store the data using sync version
            success = self.db_manager._store_record(table_name, sample_data)
            if not success:
                raise Exception("Failed to store record")
                
            # Verify data was stored
            query = f"SELECT * FROM {table_name} WHERE symbol = %s AND date = %s"
            result = execute_query(query, ('AAPL', sample_data['date']))
            
            if not result:
                raise Exception("No data found after storage")
                
            stored_record = result[0]
            
            # Convert to DataFrame to test the mapping
            df = self.db_manager.to_dataframe([stored_record])
            if df.empty:
                raise Exception("DataFrame conversion failed")
                
            # Verify key fields
            test_results = {
                'status': 'SUCCESS',
                'records_stored': len(result),
                'dataframe_rows': len(df),
                'dataframe_columns': len(df.columns),
                'has_symbol': 'symbol' in df.columns,
                'has_date': 'date' in df.columns,
                'change_field_mapped': 'change' in df.columns,  # Should be mapped back from change_amount
                'additional_fields_count': len([col for col in df.columns if col.startswith('custom_')])
            }
            
            # Check specific field mappings
            if 'change' in df.columns and df['change'].iloc[0] is not None:
                test_results['change_value_correct'] = abs(float(df['change'].iloc[0]) - 3.75) < 0.01
            
            self.log(f"✅ {entity_name}: {test_results['records_stored']} records, {test_results['dataframe_columns']} columns")
            return test_results
            
        except Exception as e:
            error_msg = str(e)
            self.log(f"❌ {entity_name}: {error_msg}", "ERROR")
            return {
                'status': 'FAILED',
                'error': error_msg,
                'traceback': traceback.format_exc()
            }
    
    def test_all_entities(self) -> Dict[str, Any]:
        """Test all 67 entities."""
        self.log("🚀 Starting comprehensive test of all 67 entities")
        
        # Get all entity names from FLATTENED_TABLES
        entities = list(FLATTENED_TABLES.keys())
        self.log(f"📋 Testing {len(entities)} entities")
        
        # Test each entity
        for entity_name in entities:
            result = self.test_entity_storage(entity_name)
            self.test_results[entity_name] = result
            
            if result['status'] == 'SUCCESS':
                self.successful_tests += 1
            else:
                self.failed_tests += 1
                
        return self.generate_summary()
    
    def generate_summary(self) -> Dict[str, Any]:
        """Generate test summary."""
        total_tests = self.successful_tests + self.failed_tests
        success_rate = (self.successful_tests / total_tests * 100) if total_tests > 0 else 0
        
        # Get failed entity details
        failed_entities = [
            entity for entity, result in self.test_results.items() 
            if result['status'] == 'FAILED'
        ]
        
        # Get success statistics
        successful_results = [
            result for result in self.test_results.values() 
            if result['status'] == 'SUCCESS'
        ]
        
        total_records = sum(r.get('records_stored', 0) for r in successful_results)
        total_df_columns = sum(r.get('dataframe_columns', 0) for r in successful_results)
        
        summary = {
            'total_entities_tested': total_tests,
            'successful_tests': self.successful_tests,
            'failed_tests': self.failed_tests,
            'success_rate_percent': round(success_rate, 2),
            'total_records_stored': total_records,
            'total_dataframe_columns': total_df_columns,
            'failed_entities': failed_entities,
            'change_field_mapping_tests': len([
                r for r in successful_results 
                if r.get('change_field_mapped', False)
            ]),
            'additional_fields_mapping_tests': len([
                r for r in successful_results 
                if r.get('additional_fields_count', 0) > 0
            ])
        }
        
        return summary


def main():
    """Main test function."""
    tester = EntityTester()
    
    try:
        # Run comprehensive test
        summary = tester.test_all_entities()
        
        # Print detailed summary
        print("\n" + "="*60)
        print("📊 COMPREHENSIVE TEST SUMMARY")
        print("="*60)
        print(f"Total Entities Tested: {summary['total_entities_tested']}")
        print(f"✅ Successful Tests: {summary['successful_tests']}")
        print(f"❌ Failed Tests: {summary['failed_tests']}")
        print(f"📈 Success Rate: {summary['success_rate_percent']}%")
        print(f"💾 Total Records Stored: {summary['total_records_stored']}")
        print(f"📋 Total DataFrame Columns: {summary['total_dataframe_columns']}")
        print(f"🔄 Change Field Mapping Tests: {summary['change_field_mapping_tests']}")
        print(f"📦 Additional Fields Tests: {summary['additional_fields_mapping_tests']}")
        
        if summary['failed_entities']:
            print(f"\n❌ Failed Entities ({len(summary['failed_entities'])}):")
            for entity in summary['failed_entities']:
                error = tester.test_results[entity].get('error', 'Unknown error')
                print(f"  - {entity}: {error}")
        else:
            print("\n🎉 All entities passed!")
            
        print("\n" + "="*60)
        
        # Verify database state
        print("\n🔍 FINAL DATABASE VERIFICATION")
        print("-" * 40)
        
        # Count total records across all tables
        total_records = 0
        for entity_name in FLATTENED_TABLES.keys():
            try:
                result = execute_query(f"SELECT COUNT(*) as count FROM {entity_name}")
                count = result[0]['count']
                total_records += count
                if count > 0:
                    print(f"  ✅ {entity_name}: {count} records")
            except Exception as e:
                print(f"  ❌ {entity_name}: Error - {e}")
                
        print(f"\n📊 Total records across all tables: {total_records}")
        
        return summary
        
    except Exception as e:
        print(f"\n❌ Test execution failed: {e}")
        traceback.print_exc()
        return None


if __name__ == "__main__":
    # Run the comprehensive test
    summary = main()
    
    if summary and summary['success_rate_percent'] == 100.0:
        print("\n🏆 ALL TESTS PASSED! Database implementation is working correctly.")
        sys.exit(0)
    else:
        print("\n⚠️  Some tests failed. Check the output above for details.")
        sys.exit(1)