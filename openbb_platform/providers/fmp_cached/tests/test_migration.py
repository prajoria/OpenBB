#!/usr/bin/env python3
"""
Migration Test Script - Quick Demo

This script demonstrates the migration process with a small sample of data
to verify the migration logic before running on the full dataset.
"""

import sys
from pathlib import Path

# Add the current directory to path
sys.path.append(str(Path(__file__).parent))

from data_migration_tool import DataMigrator, MigrationConfig

def run_test_migration():
    """Run a test migration with limited data."""
    print("🧪 MIGRATION TEST - SAMPLE DATA")
    print("="*50)
    
    # Create test configuration
    config = MigrationConfig(
        batch_size=10,  # Small batch for testing
        max_records=50,  # Limit to 50 records for testing
        dry_run=True,   # Dry run mode
        skip_existing=True,
        backup_before_migration=False  # Skip backup for test
    )
    
    print("Test Configuration:")
    print(f"  Batch Size: {config.batch_size}")
    print(f"  Max Records: {config.max_records}")
    print(f"  Dry Run: {config.dry_run}")
    print(f"  Skip Existing: {config.skip_existing}")
    
    # Run the migration
    migrator = DataMigrator(config)
    
    try:
        # Test connections
        source_conn = migrator.connect_to_database('source')
        target_conn = migrator.connect_to_database('target')
        
        if not source_conn:
            print("❌ Cannot connect to source database")
            return False
        
        if not target_conn:
            print("❌ Cannot connect to target database")
            return False
        
        print("✅ Database connections successful")
        
        # Get sample data
        print("\\n📊 Getting sample source data...")
        sample_data = migrator.get_source_data(0, 5)
        
        if sample_data:
            print(f"✅ Found {len(sample_data)} sample records")
            
            # Show sample record structure
            if sample_data:
                sample_record = sample_data[0]
                print("\\n📋 Sample source record structure:")
                for key, value in sample_record.items():
                    print(f"  {key}: {value}")
                
                # Test transformation
                print("\\n🔄 Testing record transformation...")
                transformed = migrator.transform_record(sample_record)
                
                print("\\n📋 Transformed target record:")
                for key, value in transformed.items():
                    if value is not None:
                        print(f"  {key}: {value}")
                
                print("\\n✅ Transformation test successful!")
        else:
            print("❌ No sample data found in source table")
            return False
        
        # Run actual test migration
        print("\\n🚀 Running test migration...")
        success = migrator.run_migration()
        
        return success
        
    except Exception as e:
        print(f"❌ Test migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main function for test script."""
    try:
        success = run_test_migration()
        
        if success:
            print("\\n✅ Migration test completed successfully!")
            print("\\n📝 Next steps:")
            print("  1. Review the test results")
            print("  2. Run with --dry-run=false for actual migration")
            print("  3. Use --max-records for incremental migration")
            print("  4. Use --symbols for specific symbol migration")
        else:
            print("\\n❌ Migration test failed!")
            
    except KeyboardInterrupt:
        print("\\n⚠️  Test cancelled by user")
    except Exception as e:
        print(f"\\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()