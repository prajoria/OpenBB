#!/usr/bin/env python3
"""Installation and setup script for FMP Cached provider."""

import json
import os
import subprocess
import sys
from pathlib import Path

def install_dependencies():
    """Install required Python packages."""
    print("Installing dependencies...")
    
    dependencies = [
        "aiomysql",
        "sqlalchemy>=2.0.0"
    ]
    
    for dep in dependencies:
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", dep])
            print(f"✅ Installed {dep}")
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to install {dep}: {e}")
            return False
    
    return True

def update_user_settings():
    """Update user settings with MySQL configuration template."""
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    # Create directory if it doesn't exist
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing settings or create new
    if settings_path.exists():
        with open(settings_path, 'r') as f:
            settings = json.load(f)
    else:
        settings = {"credentials": {}, "preferences": {}, "defaults": {"commands": {}}}
    
    # Check if MySQL settings already exist
    credentials = settings.get("credentials", {})
    mysql_keys = ["mysql_host", "mysql_port", "mysql_user", "mysql_password", "mysql_database"]
    
    if any(key in credentials for key in mysql_keys):
        print("✅ MySQL configuration already exists in user settings")
        return True
    
    # Add MySQL configuration template
    mysql_config = {
        "mysql_host": "localhost",
        "mysql_port": 3306,
        "mysql_user": "openbb_user",
        "mysql_password": "CHANGE_ME",
        "mysql_database": "openbb_cache"
    }
    
    credentials.update(mysql_config)
    settings["credentials"] = credentials
    
    # Write back to file
    with open(settings_path, 'w') as f:
        json.dump(settings, f, indent=4)
    
    print(f"✅ Added MySQL configuration template to {settings_path}")
    print("❗ Please update the MySQL credentials in your user_settings.json file")
    return True

def install_provider():
    """Install the FMP cached provider."""
    print("Installing FMP Cached provider...")
    
    # Get the current directory (should be the provider directory)
    provider_dir = Path(__file__).parent
    
    try:
        # Install in development mode
        subprocess.check_call([
            sys.executable, "-m", "pip", "install", "-e", str(provider_dir)
        ])
        print("✅ FMP Cached provider installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install provider: {e}")
        return False

def create_mysql_setup_script():
    """Create a MySQL setup script."""
    script_content = """-- MySQL setup script for OpenBB FMP Cached provider

-- Create database
CREATE DATABASE IF NOT EXISTS openbb_cache;

-- Create user (change password!)
CREATE USER IF NOT EXISTS 'openbb_user'@'localhost' IDENTIFIED BY 'your_secure_password_here';

-- Grant permissions
GRANT ALL PRIVILEGES ON openbb_cache.* TO 'openbb_user'@'localhost';
FLUSH PRIVILEGES;

-- Use the database
USE openbb_cache;

-- The cache tables will be created automatically by the provider
-- on first use, but you can run the following to create them manually:

-- Show databases to verify
SHOW DATABASES;

-- Show that user can access the database
SELECT 'Setup completed successfully!' as message;
"""
    
    script_path = Path(__file__).parent / "mysql_setup.sql"
    with open(script_path, 'w') as f:
        f.write(script_content)
    
    print(f"✅ Created MySQL setup script: {script_path}")
    return script_path

def main():
    """Main installation function."""
    print("🚀 Setting up FMP Cached Provider for OpenBB")
    print("=" * 50)
    
    # Step 1: Install dependencies
    if not install_dependencies():
        print("❌ Failed to install dependencies")
        return False
    
    # Step 2: Install the provider
    if not install_provider():
        print("❌ Failed to install provider")
        return False
    
    # Step 3: Update user settings
    if not update_user_settings():
        print("❌ Failed to update user settings")
        return False
    
    # Step 4: Create MySQL setup script
    mysql_script = create_mysql_setup_script()
    
    print("\n🎉 Installation completed!")
    print("=" * 50)
    print("Next steps:")
    print("1. Set up MySQL server if not already installed")
    print(f"2. Run the MySQL setup script: mysql -u root -p < {mysql_script}")
    print("3. Update MySQL credentials in ~/.openbb_platform/user_settings.json")
    print("4. Test the provider with: python test_fmp_cached.py")
    print("\nUsage:")
    print("  from openbb import obb")
    print("  data = obb.equity.price.historical('AAPL', provider='fmp_cached')")
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)