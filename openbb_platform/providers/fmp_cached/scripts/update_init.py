#!/usr/bin/env python3
"""Generate updated __init__.py file with all cached models."""

from pathlib import Path

def snake_to_pascal(snake_str):
    """Convert snake_case to PascalCase."""
    components = snake_str.split('_')
    return ''.join(word.capitalize() for word in components)

def generate_init_file():
    """Generate complete __init__.py file with all cached models."""
    models_dir = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models")
    
    # Get all model files (excluding __init__.py and base_cached.py)
    model_files = []
    for file in models_dir.glob("*.py"):
        if file.name not in ["__init__.py", "base_cached.py"]:
            model_files.append(file.stem)
    
    model_files.sort()
    
    # Generate imports and __all__ list
    imports = []
    all_exports = []
    
    for model_name in model_files:
        class_name = snake_to_pascal(model_name)
        fetcher_name = f"FMPCached{class_name}Fetcher"
        
        imports.append(f"from .{model_name} import {fetcher_name}")
        all_exports.append(f'    "{fetcher_name}",')
    
    # Create the content
    content = '"""Cached models for FMP provider."""\n\n'
    content += '\n'.join(imports)
    content += '\n\n__all__ = [\n'
    content += '\n'.join(all_exports)
    content += '\n]\n'
    
    return content

if __name__ == "__main__":
    content = generate_init_file()
    
    # Write to __init__.py
    init_file = Path("/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models/__init__.py")
    with open(init_file, 'w') as f:
        f.write(content)
    
    print(f"Updated {init_file} with all cached model imports")
    print(f"Total models imported: {len([line for line in content.split('\\n') if line.startswith('from .')])}")