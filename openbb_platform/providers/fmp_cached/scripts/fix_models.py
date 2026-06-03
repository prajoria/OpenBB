#!/usr/bin/env python3
"""Script to find correct FMP fetcher class names and fix cached models."""

import sys
import os
from pathlib import Path
import importlib

# Add FMP provider to path
sys.path.append('/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp')

def get_fetcher_class_name(module_name):
    """Get the actual fetcher class name from FMP module."""
    try:
        module = importlib.import_module(f'openbb_fmp.models.{module_name}')
        fetcher_classes = [name for name in dir(module) if name.endswith('Fetcher') and name.startswith('FMP')]
        if fetcher_classes:
            return fetcher_classes[0]  # Should be only one
        else:
            print(f"❌ No fetcher class found in {module_name}")
            return None
    except Exception as e:
        print(f"❌ Error importing {module_name}: {e}")
        return None

def snake_to_pascal(snake_str):
    """Convert snake_case to PascalCase."""
    components = snake_str.split('_')
    return ''.join(word.capitalize() for word in components)

def fix_cached_model_file(model_name, correct_fetcher_name):
    """Fix cached model file with correct fetcher class name."""
    cached_file = Path(f"/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/{model_name}.py")
    
    if not cached_file.exists():
        print(f"❌ Cached file {model_name}.py does not exist")
        return False
    
    # Determine the cached class name based on the original fetcher name
    # Remove 'FMP' prefix and add 'FMPCached' prefix
    cached_class_name = correct_fetcher_name.replace('FMP', 'FMPCached', 1)
    
    content = f'''"""Cached {model_name} model for FMP."""

from openbb_fmp.models.{model_name} import {correct_fetcher_name}
from openbb_fmp_cached.models.base_cached import create_cached_fetcher_class

# Create cached version of FMP {model_name} fetcher
{cached_class_name} = create_cached_fetcher_class(
    {correct_fetcher_name},
    "{model_name}"
)
'''
    
    with open(cached_file, 'w') as f:
        f.write(content)
    
    return cached_class_name

def main():
    """Main function to fix all cached model files."""
    models_dir = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models")
    
    # Get all cached model files
    cached_models = []
    for file in models_dir.glob("*.py"):
        if file.name not in ["__init__.py", "base_cached.py"]:
            cached_models.append(file.stem)
    
    cached_models.sort()
    
    print(f"Found {len(cached_models)} cached models to fix...")
    
    # Check each model and fix if needed
    fixed_models = {}
    errors = []
    
    for model_name in cached_models:
        print(f"Checking {model_name}...")
        correct_fetcher_name = get_fetcher_class_name(model_name)
        
        if correct_fetcher_name:
            cached_class_name = fix_cached_model_file(model_name, correct_fetcher_name)
            if cached_class_name:
                fixed_models[model_name] = cached_class_name
                print(f"  ✅ Fixed: {correct_fetcher_name} -> {cached_class_name}")
            else:
                errors.append(f"Failed to fix {model_name}")
        else:
            errors.append(f"Could not find fetcher class for {model_name}")
    
    print(f"\\n=== Summary ===")
    print(f"✅ Fixed {len(fixed_models)} models")
    if errors:
        print(f"❌ {len(errors)} errors:")
        for error in errors:
            print(f"  - {error}")
    
    return fixed_models, errors

if __name__ == "__main__":
    fixed_models, errors = main()