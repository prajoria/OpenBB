#!/usr/bin/env python3
"""Generate updated __init__.py file with correct cached model class names."""

import sys
from pathlib import Path

# Add FMP provider to path for imports
sys.path.append('/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached')

def get_cached_class_names():
    """Get all cached class names by reading the actual cached model files."""
    models_dir = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models")
    
    cached_classes = []
    model_files = []
    
    for file in models_dir.glob("*.py"):
        if file.name not in ["__init__.py", "base_cached.py"]:
            model_files.append(file.stem)
    
    model_files.sort()
    
    for model_name in model_files:
        # Read the file to find the cached class name
        model_file = models_dir / f"{model_name}.py"
        try:
            with open(model_file, 'r') as f:
                content = f.read()
                
            # Find the line that defines the cached class
            for line in content.split('\n'):
                if '= create_cached_fetcher_class(' in line and 'FMPCached' in line:
                    class_name = line.split('=')[0].strip()
                    cached_classes.append((model_name, class_name))
                    break
            else:
                print(f"⚠️  Could not find cached class in {model_name}.py")
                
        except Exception as e:
            print(f"❌ Error reading {model_name}.py: {e}")
    
    return cached_classes

def generate_init_content(cached_classes):
    """Generate the complete __init__.py content."""
    imports = []
    all_exports = []
    
    for model_name, class_name in cached_classes:
        imports.append(f"from .{model_name} import {class_name}")
        all_exports.append(f'    "{class_name}",')
    
    content = '"""Cached models for FMP provider."""\n\n'
    content += '\n'.join(imports)
    content += '\n\n__all__ = [\n'
    content += '\n'.join(all_exports)
    content += '\n]\n'
    
    return content

def main():
    """Main function to generate __init__.py."""
    print("Reading cached model files to determine class names...")
    
    cached_classes = get_cached_class_names()
    
    if not cached_classes:
        print("❌ No cached classes found!")
        return
    
    print(f"Found {len(cached_classes)} cached classes")
    
    # Generate new __init__.py content
    content = generate_init_content(cached_classes)
    
    # Write to __init__.py
    init_file = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/__init__.py")
    with open(init_file, 'w') as f:
        f.write(content)
    
    print(f"✅ Updated {init_file} with {len(cached_classes)} cached model imports")
    
    # Show first few classes as verification
    print("\\nFirst 5 classes:")
    for i, (model_name, class_name) in enumerate(cached_classes[:5], 1):
        print(f"  {i}. {model_name} -> {class_name}")

if __name__ == "__main__":
    main()