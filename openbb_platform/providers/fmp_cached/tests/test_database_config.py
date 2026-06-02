"""Test script for FMP cached database configuration.

This script helps users test and configure their MySQL database credentials
for the FMP cached provider.

Usage:
    python test_database_config.py
"""

import json
import os
import sys
from pathlib import Path

# Add provider to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from openbb_fmp_cached.utils.database import DatabaseConfig, init_database


class Colors:
    """Console colors."""
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'


def print_header(title: str):
    """Print formatted header."""
    print(f"\n{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{title:^60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.CYAN}{'='*60}{Colors.END}")


def print_success(msg: str):
    """Print success message."""
    print(f"{Colors.GREEN}✅ {msg}{Colors.END}")


def print_error(msg: str):
    """Print error message."""
    print(f"{Colors.RED}❌ {msg}{Colors.END}")


def print_info(msg: str):
    """Print info message."""
    print(f"{Colors.BLUE}ℹ️  {msg}{Colors.END}")


def print_warning(msg: str):
    """Print warning message."""
    print(f"{Colors.YELLOW}⚠️  {msg}{Colors.END}")


def check_user_settings_file():
    """Check if user settings file exists and show its content."""
    print_header("Checking OpenBB User Settings File")
    
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    
    if not os.path.exists(settings_path):
        print_error("OpenBB user settings file not found")
        print_info(f"Expected location: {settings_path}")
        return None
    
    try:
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        
        print_success(f"User settings file found: {settings_path}")
        
        credentials = settings.get("credentials", {})
        if not credentials:
            print_warning("No credentials section found in user settings")
            return settings
        
        # Check for database credentials
        db_keys = [
            "mysql_host", "mysql_user", "mysql_password", "mysql_database",
            "db_host", "db_user", "db_password", "db_database",
            "database_host", "database_user", "database_password", "database_name"
        ]
        
        found_db_keys = [key for key in db_keys if key in credentials]
        
        if found_db_keys:
            print_success("Database credentials found:")
            for key in found_db_keys:
                value = credentials[key]
                if "password" in key.lower():
                    masked_value = "*" * len(str(value)) if value else "empty"
                    print_info(f"  {key}: {masked_value}")
                else:
                    print_info(f"  {key}: {value}")
        else:
            print_warning("No database credentials found in user settings")
        
        return settings
        
    except Exception as e:
        print_error(f"Error reading user settings: {e}")
        return None


def test_database_config():
    """Test the database configuration."""
    print_header("Testing Database Configuration")
    
    try:
        config = DatabaseConfig()
        db_config = config.config
        
        print_success("Database configuration loaded:")
        for key, value in db_config.items():
            if "password" in key.lower():
                masked_value = "*" * len(str(value)) if value else "empty"
                print_info(f"  {key}: {masked_value}")
            else:
                print_info(f"  {key}: {value}")
        
        return db_config
        
    except Exception as e:
        print_error(f"Error loading database configuration: {e}")
        return None


def test_database_connection():
    """Test the database connection."""
    print_header("Testing Database Connection")
    
    try:
        print_info("Attempting to initialize database...")
        init_database()
        print_success("Database connection successful!")
        return True
        
    except Exception as e:
        print_error(f"Database connection failed: {e}")
        return False


def show_configuration_examples():
    """Show example configurations."""
    print_header("Configuration Examples")
    
    print_info("Add database credentials to ~/.openbb_platform/user_settings.json:")
    
    print(f"\n{Colors.YELLOW}Example 1 - Using mysql_ prefix:{Colors.END}")
    example1 = {
        "credentials": {
            "fmp_api_key": "your_fmp_api_key_here",
            "mysql_host": "localhost",
            "mysql_port": 3306,
            "mysql_user": "your_username",
            "mysql_password": "your_password",
            "mysql_database": "openbb_fmp_cache"
        }
    }
    print(json.dumps(example1, indent=2))
    
    print(f"\n{Colors.YELLOW}Example 2 - Using db_ prefix:{Colors.END}")
    example2 = {
        "credentials": {
            "fmp_api_key": "your_fmp_api_key_here",
            "db_host": "localhost",
            "db_port": 3306,
            "db_user": "your_username",
            "db_password": "your_password",
            "db_database": "openbb_fmp_cache"
        }
    }
    print(json.dumps(example2, indent=2))
    
    print(f"\n{Colors.YELLOW}Example 3 - For testing (uses test database):{Colors.END}")
    print("Set environment variable: FMP_CACHE_TEST_MODE=true")
    example3 = {
        "credentials": {
            "fmp_api_key": "your_fmp_api_key_here",
            "mysql_host": "localhost",
            "mysql_user": "your_username",
            "mysql_password": "your_password",
            "mysql_database": "openbb_fmp_cache_test"
        }
    }
    print(json.dumps(example3, indent=2))


def create_sample_settings():
    """Create a sample user settings file."""
    print_header("Create Sample Settings File")
    
    settings_path = os.path.expanduser("~/.openbb_platform/user_settings.json")
    
    if os.path.exists(settings_path):
        print_warning("User settings file already exists")
        response = input("Do you want to see the current content? (y/n): ").lower().strip()
        if response == 'y':
            try:
                with open(settings_path, 'r') as f:
                    content = f.read()
                print("\nCurrent content:")
                print(content)
            except Exception as e:
                print_error(f"Error reading file: {e}")
        return
    
    print_info(f"Creating sample settings file: {settings_path}")
    
    # Create directory if it doesn't exist
    os.makedirs(os.path.dirname(settings_path), exist_ok=True)
    
    # Sample settings
    sample_settings = {
        "credentials": {
            "fmp_api_key": "your_fmp_api_key_here",
            "mysql_host": "localhost",
            "mysql_port": 3306,
            "mysql_user": "your_mysql_username",
            "mysql_password": "your_mysql_password",
            "mysql_database": "openbb_fmp_cache"
        },
        "preferences": {},
        "defaults": {"commands": {}}
    }
    
    try:
        with open(settings_path, 'w') as f:
            json.dump(sample_settings, f, indent=2)
        
        print_success("Sample settings file created!")
        print_warning("Please edit the file and add your actual credentials")
        print_info("Required credentials:")
        print_info("  - fmp_api_key: Get from https://financialmodelingprep.com/")
        print_info("  - mysql_*: Your MySQL database credentials")
        
    except Exception as e:
        print_error(f"Error creating settings file: {e}")


def main():
    """Main test function."""
    print_header("FMP Cached Provider - Database Configuration Test")
    
    # Check if test mode is enabled
    test_mode = os.getenv("FMP_CACHE_TEST_MODE", "false").lower() == "true"
    if test_mode:
        print_info("🧪 Test mode enabled (will use openbb_fmp_cache_test database)")
    
    # Check user settings file
    settings = check_user_settings_file()
    
    if settings is None:
        print_info("\nWould you like to create a sample settings file?")
        response = input("Create sample file? (y/n): ").lower().strip()
        if response == 'y':
            create_sample_settings()
        else:
            show_configuration_examples()
        return
    
    # Test database configuration
    config = test_database_config()
    
    if config is None:
        show_configuration_examples()
        return
    
    # Test database connection
    connection_success = test_database_connection()
    
    # Summary
    print_header("Summary")
    
    if connection_success:
        print_success("✨ Database configuration is working!")
        print_info("You can now use the FMP cached provider with database caching")
    else:
        print_error("❌ Database connection failed")
        print_info("Please check your database credentials and ensure MySQL server is running")
        print_info("You can still use the FMP cached provider with in-memory caching")
    
    print_info("\n💡 Tip: Set FMP_CACHE_TEST_MODE=true for testing scenarios")


if __name__ == "__main__":
    main()