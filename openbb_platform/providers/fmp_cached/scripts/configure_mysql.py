#!/usr/bin/env python3
"""Script to configure MySQL settings in OpenBB user settings."""

import json
import os
from pathlib import Path

def update_user_settings():
    """Update OpenBB user settings with MySQL configuration."""
    
    # MySQL configuration
    mysql_config = {
        "mysql_host": "localhost",
        "mysql_port": "3306",  # Store as string for OpenBB compatibility
        "mysql_user": "fmp_user", 
        "mysql_password": "fmp_password",
        "mysql_database": "openbb_fmp_cache"
    }
    
    print("📝 Updating OpenBB user settings with MySQL configuration...")
    
    # Path to user settings
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    if not settings_path.parent.exists():
        print("Creating OpenBB platform directory...")
        settings_path.parent.mkdir(parents=True, exist_ok=True)
    
    # Load existing settings
    settings = {}
    if settings_path.exists():
        try:
            with open(settings_path, 'r') as f:
                settings = json.load(f)
            print("✅ Loaded existing user settings")
        except Exception as e:
            print(f"⚠️  Could not load existing settings: {e}")
            settings = {}
    
    # Ensure credentials section exists
    if "credentials" not in settings:
        settings["credentials"] = {}
    
    # Add MySQL credentials
    print("Adding MySQL credentials...")
    settings["credentials"].update(mysql_config)
    
    # Save updated settings
    try:
        with open(settings_path, 'w') as f:
            json.dump(settings, f, indent=4)
        print("✅ User settings updated successfully!")
        
        print(f"\n📋 MySQL Configuration Added:")
        for key, value in mysql_config.items():
            masked_value = "*" * len(str(value)) if "password" in key.lower() else value
            print(f"   {key}: {masked_value}")
            
        return True
        
    except Exception as e:
        print(f"❌ Failed to save user settings: {e}")
        return False

def verify_settings():
    """Verify that the MySQL settings were saved correctly."""
    print("\n🔍 Verifying MySQL settings in user settings...")
    
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    try:
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        
        credentials = settings.get("credentials", {})
        mysql_keys = ["mysql_host", "mysql_port", "mysql_user", "mysql_password", "mysql_database"]
        
        missing_keys = [key for key in mysql_keys if key not in credentials]
        
        if missing_keys:
            print(f"❌ Missing MySQL keys: {missing_keys}")
            return False
        else:
            print("✅ All MySQL settings found in user settings")
            return True
            
    except Exception as e:
        print(f"❌ Could not verify settings: {e}")
        return False

def show_current_settings():
    """Show current user settings (with password masked)."""
    print("\n📖 Current OpenBB User Settings:")
    
    settings_path = Path.home() / ".openbb_platform" / "user_settings.json"
    
    try:
        with open(settings_path, 'r') as f:
            settings = json.load(f)
        
        # Mask passwords for display
        display_settings = json.loads(json.dumps(settings))  # Deep copy
        credentials = display_settings.get("credentials", {})
        
        for key in credentials:
            if "password" in key.lower() or "key" in key.lower():
                credentials[key] = "*" * len(str(credentials[key]))
        
        print(json.dumps(display_settings, indent=2))
        
    except Exception as e:
        print(f"❌ Could not read settings: {e}")

if __name__ == "__main__":
    print("🚀 OpenBB MySQL Configuration Setup")
    print("=" * 40)
    
    # Update settings
    if update_user_settings():
        # Verify settings
        if verify_settings():
            show_current_settings()
            
            print("\n🎉 MySQL configuration setup complete!")
            print("\n🎯 Next steps:")
            print("   1. Make sure MySQL server is running")
            print("   2. Create the database and user (run setup_database.py)")
            print("   3. Test the configuration (run test_fmp_cached.py)")
        else:
            print("❌ Settings verification failed!")
    else:
        print("❌ Settings update failed!")