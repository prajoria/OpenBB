#!/usr/bin/env python3
"""
Table Structure Comparison: equity_historical vs equity_screener

This script analyzes and compares the database table structures and data content
between equity_historical and equity_screener tables to determine similarities
and differences in the type of information they store.
"""

import sys
import pandas as pd
from datetime import datetime, date, timedelta
from typing import Dict, List, Any, Optional
from pathlib import Path

# Add the FMP cached provider to path
sys.path.append('/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached')

from openbb_fmp_cached.utils.database import execute_query


class TableComparisonAnalyzer:
    """Analyzes and compares database table structures and data."""
    
    def __init__(self):
        self.equity_historical_columns = []
        self.equity_screener_columns = []
        self.sample_data = {}
    
    def get_table_structure(self, table_name: str) -> List[Dict[str, Any]]:
        """Get the structure of a database table."""
        try:
            result = execute_query(f"DESCRIBE {table_name}")
            if result:
                return [dict(row) for row in result] if isinstance(result, list) else [dict(result)]
            return []
        except Exception as e:
            print(f"❌ Error getting structure for {table_name}: {e}")
            return []
    
    def get_sample_data(self, table_name: str, limit: int = 5) -> List[Dict[str, Any]]:
        """Get sample data from a table."""
        try:
            result = execute_query(f"SELECT * FROM {table_name} WHERE is_valid = TRUE LIMIT {limit}")
            if result:
                return [dict(row) for row in result] if isinstance(result, list) else [dict(result)]
            return []
        except Exception as e:
            print(f"❌ Error getting sample data for {table_name}: {e}")
            return []
    
    def get_table_stats(self, table_name: str) -> Dict[str, Any]:
        """Get statistics about a table."""
        try:
            stats = {}
            
            # Total record count
            count_result = execute_query(f"SELECT COUNT(*) as total_records FROM {table_name}")
            stats['total_records'] = list(count_result[0].values())[0] if count_result else 0
            
            # Valid records count
            valid_count_result = execute_query(f"SELECT COUNT(*) as valid_records FROM {table_name} WHERE is_valid = TRUE")
            stats['valid_records'] = list(valid_count_result[0].values())[0] if valid_count_result else 0
            
            # Unique symbols
            symbol_count_result = execute_query(f"SELECT COUNT(DISTINCT symbol) as unique_symbols FROM {table_name} WHERE symbol IS NOT NULL")
            stats['unique_symbols'] = list(symbol_count_result[0].values())[0] if symbol_count_result else 0
            
            # Date range
            date_range_result = execute_query(f"SELECT MIN(date) as min_date, MAX(date) as max_date FROM {table_name} WHERE date IS NOT NULL")
            if date_range_result and date_range_result[0]:
                row_dict = dict(date_range_result[0])
                stats['min_date'] = row_dict.get('min_date')
                stats['max_date'] = row_dict.get('max_date')
            
            return stats
        except Exception as e:
            print(f"❌ Error getting stats for {table_name}: {e}")
            return {}
    
    def analyze_column_overlap(self) -> Dict[str, Any]:
        """Analyze column overlap between tables."""
        hist_cols = set(col['Field'] for col in self.equity_historical_columns)
        screen_cols = set(col['Field'] for col in self.equity_screener_columns)
        
        common_columns = hist_cols.intersection(screen_cols)
        hist_only = hist_cols - screen_cols
        screen_only = screen_cols - hist_cols
        
        return {
            'common_columns': sorted(common_columns),
            'equity_historical_only': sorted(hist_only),
            'equity_screener_only': sorted(screen_only),
            'total_common': len(common_columns),
            'hist_total': len(hist_cols),
            'screen_total': len(screen_cols),
            'overlap_percentage': (len(common_columns) / len(hist_cols.union(screen_cols))) * 100
        }
    
    def categorize_columns(self, columns: List[Dict[str, Any]]) -> Dict[str, List[str]]:
        """Categorize columns by their data type and purpose."""
        categories = {
            'identifiers': [],
            'pricing_data': [],
            'volume_data': [],
            'company_info': [],
            'financial_metrics': [],
            'ratios': [],
            'metadata': [],
            'other': []
        }
        
        for col in columns:
            field_name = col['Field'].lower()
            
            if field_name in ['id', 'symbol', 'date', 'period', 'currency', 'exchange']:
                categories['identifiers'].append(col['Field'])
            elif field_name in ['open', 'high', 'low', 'close', 'price', 'vwap']:
                categories['pricing_data'].append(col['Field'])
            elif field_name in ['volume']:
                categories['volume_data'].append(col['Field'])
            elif field_name in ['company_name', 'sector', 'industry', 'country', 'description', 'ceo', 'employees', 'website']:
                categories['company_info'].append(col['Field'])
            elif field_name in ['revenue', 'cost_of_revenue', 'gross_profit', 'operating_expenses', 'operating_income', 
                               'net_income', 'eps', 'eps_diluted', 'total_assets', 'total_liabilities', 'total_equity',
                               'cash_and_cash_equivalents', 'total_debt', 'working_capital', 'operating_cash_flow',
                               'investing_cash_flow', 'financing_cash_flow', 'free_cash_flow', 'capital_expenditure']:
                categories['financial_metrics'].append(col['Field'])
            elif 'ratio' in field_name or field_name in ['pe_ratio', 'pb_ratio', 'debt_to_equity', 'current_ratio', 'roe', 'roa', 'beta']:
                categories['ratios'].append(col['Field'])
            elif field_name in ['cached_at', 'is_valid', 'data_json', 'additional_fields']:
                categories['metadata'].append(col['Field'])
            else:
                categories['other'].append(col['Field'])
        
        return categories
    
    def analyze_data_completeness(self, table_name: str, sample_data: List[Dict]) -> Dict[str, Any]:
        """Analyze data completeness for sample records."""
        if not sample_data:
            return {'null_percentages': {}, 'total_fields': 0, 'avg_completeness': 0}
        
        total_records = len(sample_data)
        field_null_counts = {}
        
        # Get all fields from first record
        if sample_data:
            all_fields = sample_data[0].keys()
            
            for field in all_fields:
                null_count = sum(1 for record in sample_data if record.get(field) is None)
                field_null_counts[field] = (null_count / total_records) * 100
        
        avg_completeness = 100 - (sum(field_null_counts.values()) / len(field_null_counts))
        
        return {
            'null_percentages': field_null_counts,
            'total_fields': len(field_null_counts),
            'avg_completeness': avg_completeness,
            'most_complete_fields': sorted(field_null_counts.items(), key=lambda x: x[1])[:5],
            'least_complete_fields': sorted(field_null_counts.items(), key=lambda x: x[1], reverse=True)[:5]
        }
    
    def run_comparison(self) -> None:
        """Run comprehensive comparison analysis."""
        print("🔍 DATABASE TABLE COMPARISON ANALYSIS")
        print("="*60)
        print("Comparing equity_historical vs equity_screener tables")
        print("="*60)
        
        # Get table structures
        print("\n📋 Fetching table structures...")
        self.equity_historical_columns = self.get_table_structure('equity_historical')
        self.equity_screener_columns = self.get_table_structure('equity_screener')
        
        if not self.equity_historical_columns:
            print("❌ Could not retrieve equity_historical table structure")
            return
        
        if not self.equity_screener_columns:
            print("❌ Could not retrieve equity_screener table structure")
            return
        
        print(f"✅ equity_historical: {len(self.equity_historical_columns)} columns")
        print(f"✅ equity_screener: {len(self.equity_screener_columns)} columns")
        
        # Get table statistics
        print("\n📊 Gathering table statistics...")
        hist_stats = self.get_table_stats('equity_historical')
        screen_stats = self.get_table_stats('equity_screener')
        
        # Get sample data
        print("\n📄 Fetching sample data...")
        hist_sample = self.get_sample_data('equity_historical', 10)
        screen_sample = self.get_sample_data('equity_screener', 10)
        
        print(f"✅ equity_historical sample: {len(hist_sample)} records")
        print(f"✅ equity_screener sample: {len(screen_sample)} records")
        
        # Analyze column overlap
        print("\n🔗 Analyzing column overlap...")
        overlap_analysis = self.analyze_column_overlap()
        
        # Categorize columns
        print("\n📂 Categorizing columns...")
        hist_categories = self.categorize_columns(self.equity_historical_columns)
        screen_categories = self.categorize_columns(self.equity_screener_columns)
        
        # Analyze data completeness
        print("\n📈 Analyzing data completeness...")
        hist_completeness = self.analyze_data_completeness('equity_historical', hist_sample)
        screen_completeness = self.analyze_data_completeness('equity_screener', screen_sample)
        
        # Display results
        self.display_results(
            hist_stats, screen_stats, 
            overlap_analysis, 
            hist_categories, screen_categories,
            hist_completeness, screen_completeness,
            hist_sample, screen_sample
        )
    
    def display_results(self, hist_stats, screen_stats, overlap_analysis, 
                       hist_categories, screen_categories, hist_completeness, 
                       screen_completeness, hist_sample, screen_sample):
        """Display comprehensive comparison results."""
        
        print("\n" + "="*80)
        print("📊 COMPREHENSIVE TABLE COMPARISON RESULTS")
        print("="*80)
        
        # Table Statistics Comparison
        print("\n📈 TABLE STATISTICS COMPARISON")
        print("-"*50)
        print(f"{'Metric':<25} {'equity_historical':<20} {'equity_screener':<20}")
        print("-"*65)
        print(f"{'Total Records':<25} {hist_stats.get('total_records', 0):<20} {screen_stats.get('total_records', 0):<20}")
        print(f"{'Valid Records':<25} {hist_stats.get('valid_records', 0):<20} {screen_stats.get('valid_records', 0):<20}")
        print(f"{'Unique Symbols':<25} {hist_stats.get('unique_symbols', 0):<20} {screen_stats.get('unique_symbols', 0):<20}")
        print(f"{'Date Range (Start)':<25} {str(hist_stats.get('min_date', 'N/A')):<20} {str(screen_stats.get('min_date', 'N/A')):<20}")
        print(f"{'Date Range (End)':<25} {str(hist_stats.get('max_date', 'N/A')):<20} {str(screen_stats.get('max_date', 'N/A')):<20}")
        
        # Schema Overlap Analysis
        print(f"\n🔗 SCHEMA OVERLAP ANALYSIS")
        print("-"*50)
        print(f"Total Columns in equity_historical: {overlap_analysis['hist_total']}")
        print(f"Total Columns in equity_screener: {overlap_analysis['screen_total']}")
        print(f"Common Columns: {overlap_analysis['total_common']}")
        print(f"Schema Overlap Percentage: {overlap_analysis['overlap_percentage']:.1f}%")
        
        print(f"\n📋 Common Columns ({len(overlap_analysis['common_columns'])} total):")
        for i, col in enumerate(overlap_analysis['common_columns']):
            if i % 4 == 0:
                print()
            print(f"  {col:<18}", end="")
        
        if overlap_analysis['equity_historical_only']:
            print(f"\n\n📋 Columns ONLY in equity_historical ({len(overlap_analysis['equity_historical_only'])} total):")
            for i, col in enumerate(overlap_analysis['equity_historical_only']):
                if i % 4 == 0:
                    print()
                print(f"  {col:<18}", end="")
        
        if overlap_analysis['equity_screener_only']:
            print(f"\n\n📋 Columns ONLY in equity_screener ({len(overlap_analysis['equity_screener_only'])} total):")
            for i, col in enumerate(overlap_analysis['equity_screener_only']):
                if i % 4 == 0:
                    print()
                print(f"  {col:<18}", end="")
        
        # Column Categories Comparison
        print(f"\n\n📂 COLUMN CATEGORIES COMPARISON")
        print("-"*50)
        categories = ['identifiers', 'pricing_data', 'volume_data', 'company_info', 'financial_metrics', 'ratios', 'metadata']
        
        print(f"{'Category':<20} {'equity_historical':<20} {'equity_screener':<20}")
        print("-"*60)
        for category in categories:
            hist_count = len(hist_categories.get(category, []))
            screen_count = len(screen_categories.get(category, []))
            print(f"{category.replace('_', ' ').title():<20} {hist_count:<20} {screen_count:<20}")
        
        # Data Completeness Analysis
        print(f"\n📈 DATA COMPLETENESS ANALYSIS")
        print("-"*50)
        print(f"{'Table':<20} {'Avg Completeness':<20} {'Total Fields':<15}")
        print("-"*55)
        print(f"{'equity_historical':<20} {hist_completeness.get('avg_completeness', 0):<19.1f}% {hist_completeness.get('total_fields', 0):<15}")
        print(f"{'equity_screener':<20} {screen_completeness.get('avg_completeness', 0):<19.1f}% {screen_completeness.get('total_fields', 0):<15}")
        
        # Most/Least Complete Fields
        if hist_completeness.get('most_complete_fields'):
            print(f"\n📊 Most Complete Fields in equity_historical:")
            for field, null_pct in hist_completeness['most_complete_fields']:
                print(f"  {field:<25} {100-null_pct:>6.1f}% complete")
        
        if screen_completeness.get('most_complete_fields'):
            print(f"\n📊 Most Complete Fields in equity_screener:")
            for field, null_pct in screen_completeness['most_complete_fields']:
                print(f"  {field:<25} {100-null_pct:>6.1f}% complete")
        
        # Key Insights and Conclusions
        print(f"\n🔍 KEY INSIGHTS AND CONCLUSIONS")
        print("="*50)
        
        # Schema similarity
        if overlap_analysis['overlap_percentage'] > 90:
            schema_similarity = "NEARLY IDENTICAL"
        elif overlap_analysis['overlap_percentage'] > 70:
            schema_similarity = "VERY SIMILAR"
        elif overlap_analysis['overlap_percentage'] > 50:
            schema_similarity = "MODERATELY SIMILAR"
        else:
            schema_similarity = "QUITE DIFFERENT"
        
        print(f"📋 Schema Similarity: {schema_similarity} ({overlap_analysis['overlap_percentage']:.1f}% overlap)")
        
        # Data volume comparison
        hist_records = hist_stats.get('total_records', 0)
        screen_records = screen_stats.get('total_records', 0)
        
        if hist_records > screen_records * 2:
            data_volume = "equity_historical has SIGNIFICANTLY more data"
        elif screen_records > hist_records * 2:
            data_volume = "equity_screener has SIGNIFICANTLY more data"
        elif abs(hist_records - screen_records) < max(hist_records, screen_records) * 0.1:
            data_volume = "Both tables have SIMILAR data volumes"
        else:
            data_volume = f"Moderate difference in data volume"
        
        print(f"📊 Data Volume: {data_volume}")
        
        # Purpose analysis based on column categories
        hist_has_more_financial = len(hist_categories.get('financial_metrics', [])) > len(screen_categories.get('financial_metrics', []))
        screen_has_more_financial = len(screen_categories.get('financial_metrics', [])) > len(hist_categories.get('financial_metrics', []))
        
        if hist_has_more_financial:
            purpose_analysis = "equity_historical appears more focused on comprehensive financial data"
        elif screen_has_more_financial:
            purpose_analysis = "equity_screener appears more focused on comprehensive financial data"
        else:
            purpose_analysis = "Both tables serve similar financial data purposes"
        
        print(f"🎯 Purpose Analysis: {purpose_analysis}")
        
        # Final conclusion
        print(f"\n🏁 FINAL CONCLUSION")
        print("-"*30)
        
        if overlap_analysis['overlap_percentage'] > 95 and abs(hist_records - screen_records) < max(hist_records, screen_records) * 0.1:
            conclusion = "The tables are ESSENTIALLY THE SAME - they store the same type of information with nearly identical structures and similar data volumes."
        elif overlap_analysis['overlap_percentage'] > 80:
            conclusion = "The tables store VERY SIMILAR information with high schema overlap, likely serving related but distinct purposes in the financial data pipeline."
        elif overlap_analysis['overlap_percentage'] > 60:
            conclusion = "The tables store RELATED information with significant schema overlap, but have distinct purposes and may contain different aspects of financial data."
        else:
            conclusion = "The tables store DIFFERENT types of information despite some common fields, serving distinct purposes in the system."
        
        print(f"{conclusion}")
        
        # Specific differences if any
        unique_hist_cols = overlap_analysis['equity_historical_only']
        unique_screen_cols = overlap_analysis['equity_screener_only']
        
        if unique_hist_cols or unique_screen_cols:
            print(f"\n⚠️  Key Differences:")
            if unique_hist_cols:
                print(f"   - equity_historical has {len(unique_hist_cols)} unique columns")
            if unique_screen_cols:
                print(f"   - equity_screener has {len(unique_screen_cols)} unique columns")
        
        print(f"\n" + "="*80)
        print("Analysis complete! ✅")
        print("="*80)


def main():
    """Main function to run the table comparison analysis."""
    print("🚀 Starting Table Comparison Analysis...")
    
    try:
        analyzer = TableComparisonAnalyzer()
        analyzer.run_comparison()
        
    except Exception as e:
        print(f"❌ Error during analysis: {e}")
        import traceback
        traceback.print_exc()
        return False
    
    return True


if __name__ == "__main__":
    try:
        success = main()
        if success:
            print("\n✅ Table comparison analysis completed successfully!")
        else:
            print("\n❌ Table comparison analysis failed")
            sys.exit(1)
    except KeyboardInterrupt:
        print("\n⚠️  Analysis cancelled by user")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)