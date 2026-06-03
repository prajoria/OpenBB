#!/usr/bin/env python3
"""
Migration Execution Scripts

This provides ready-to-use migration scenarios for different use cases.
"""

import subprocess
import sys
from datetime import datetime, timedelta

def run_command(command):
    """Run a command and display output."""
    print(f"🚀 Running: {command}")
    print("-" * 60)
    
    try:
        result = subprocess.run(command, shell=True, capture_output=True, text=True)
        
        if result.stdout:
            print(result.stdout)
        
        if result.stderr:
            print("STDERR:", result.stderr)
        
        print("-" * 60)
        print(f"Exit code: {result.returncode}")
        
        return result.returncode == 0
        
    except Exception as e:
        print(f"Error running command: {e}")
        return False


def scenario_1_dry_run_sample():
    """Scenario 1: Dry run with small sample (recommended first step)."""
    print("📋 SCENARIO 1: DRY RUN SAMPLE MIGRATION")
    print("="*60)
    print("Purpose: Test the migration logic with a small sample")
    print("Safety: High - No actual data changes")
    print("="*60)
    
    command = "python data_migration_tool.py --dry-run --max-records 100 --batch-size 10"
    return run_command(command)


def scenario_2_recent_data():
    """Scenario 2: Migrate recent data (last 30 days)."""
    print("📋 SCENARIO 2: RECENT DATA MIGRATION")
    print("="*60)
    print("Purpose: Migrate recent historical data (last 30 days)")
    print("Safety: Medium - Limited date range")
    print("="*60)
    
    # Calculate date 30 days ago
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    
    command = f"python data_migration_tool.py --start-date {start_date} --end-date {end_date} --batch-size 1000"
    return run_command(command)


def scenario_3_specific_symbols():
    """Scenario 3: Migrate specific symbols."""
    print("📋 SCENARIO 3: SPECIFIC SYMBOLS MIGRATION")
    print("="*60)
    print("Purpose: Migrate data for specific symbols only")
    print("Safety: Medium - Limited to specific symbols")
    print("="*60)
    
    symbols = input("Enter symbols (space-separated, e.g., AAPL TSLA MSFT): ").strip()
    if not symbols:
        print("No symbols provided. Skipping.")
        return False
    
    command = f"python data_migration_tool.py --symbols {symbols} --batch-size 1000"
    return run_command(command)


def scenario_4_incremental():
    """Scenario 4: Incremental migration (limited records)."""
    print("📋 SCENARIO 4: INCREMENTAL MIGRATION")
    print("="*60)
    print("Purpose: Migrate a limited number of records incrementally")
    print("Safety: Medium - Limited record count")
    print("="*60)
    
    max_records = input("Enter max records to migrate (e.g., 10000): ").strip()
    try:
        max_records = int(max_records)
    except:
        print("Invalid number. Using default 10000.")
        max_records = 10000
    
    command = f"python data_migration_tool.py --max-records {max_records} --batch-size 1000"
    return run_command(command)


def scenario_5_full_migration():
    """Scenario 5: Full migration (all data)."""
    print("📋 SCENARIO 5: FULL MIGRATION")
    print("="*60)
    print("Purpose: Migrate ALL historical data")
    print("Safety: LOW - Will migrate entire dataset (~1.18M records)")
    print("="*60)
    
    print("⚠️  WARNING: This will migrate all 1.18M records!")
    print("This may take a considerable amount of time.")
    
    confirm = input("Are you sure you want to proceed? Type 'YES' to confirm: ")
    if confirm != 'YES':
        print("Full migration cancelled.")
        return False
    
    command = "python data_migration_tool.py --batch-size 5000"
    return run_command(command)


def main():
    """Main menu for migration scenarios."""
    print("🔄 DATA MIGRATION SCENARIOS")
    print("="*60)
    print("Source: fmp_cache.historical_prices_daily")
    print("Target: openbb_fmp_cache.equity_screener")
    print("="*60)
    
    scenarios = [
        ("1", "Dry Run Sample (100 records, no changes)", scenario_1_dry_run_sample),
        ("2", "Recent Data (Last 30 days)", scenario_2_recent_data),
        ("3", "Specific Symbols", scenario_3_specific_symbols),
        ("4", "Incremental Migration (Limited records)", scenario_4_incremental),
        ("5", "Full Migration (ALL data - ~1.18M records)", scenario_5_full_migration),
    ]
    
    print("Available scenarios:")
    for num, desc, _ in scenarios:
        print(f"  {num}. {desc}")
    
    print("\\n📝 Recommendations:")
    print("  - Always start with Scenario 1 (Dry Run) to test")
    print("  - Use Scenario 2 or 3 for production deployment")
    print("  - Only use Scenario 5 for complete data migration")
    
    while True:
        choice = input("\\nSelect scenario (1-5, or 'q' to quit): ").strip()
        
        if choice.lower() == 'q':
            print("Goodbye!")
            break
        
        # Find matching scenario
        scenario_func = None
        for num, desc, func in scenarios:
            if choice == num:
                scenario_func = func
                break
        
        if scenario_func:
            print(f"\\n🎯 Executing scenario {choice}...")
            success = scenario_func()
            
            if success:
                print(f"\\n✅ Scenario {choice} completed successfully!")
            else:
                print(f"\\n❌ Scenario {choice} failed!")
            
            # Ask if user wants to continue
            continue_choice = input("\\nRun another scenario? (y/N): ")
            if continue_choice.lower() != 'y':
                break
        else:
            print("Invalid choice. Please select 1-5 or 'q' to quit.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\\n⚠️  Migration scenarios cancelled by user")
    except Exception as e:
        print(f"\\n❌ Error: {e}")
        sys.exit(1)