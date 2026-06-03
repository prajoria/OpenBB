#!/usr/bin/env python3
"""Script to verify 1:1 mapping between FMP and FMP Cached models."""

from pathlib import Path

def get_model_files(directory):
    """Get all Python model files from directory (excluding __init__.py and base files)."""
    path = Path(directory)
    files = set()
    for file in path.glob("*.py"):
        if file.name not in ["__init__.py", "base_cached.py"]:
            files.add(file.stem)
    return files

# Get FMP models
fmp_models_dir = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp/openbb_fmp/models"
fmp_models = get_model_files(fmp_models_dir)

# Get FMP Cached models
cached_models_dir = "/home/daaji/masterswork/git/OpenBB/openbb_platform/providers/fmp_cached/openbb_fmp_cached/models"
cached_models = get_model_files(cached_models_dir)

print("=== FMP Cached Provider Model Mapping Verification ===\n")

print(f"FMP Models: {len(fmp_models)} files")
print(f"FMP Cached Models: {len(cached_models)} files")
print()

# Check for missing cached models
missing_cached = fmp_models - cached_models
if missing_cached:
    print(f"❌ Missing Cached Models ({len(missing_cached)}):")
    for model in sorted(missing_cached):
        print(f"  - {model}.py")
    print()
else:
    print("✅ All FMP models have cached versions!")
    print()

# Check for extra cached models (shouldn't happen but good to verify)
extra_cached = cached_models - fmp_models
if extra_cached:
    print(f"⚠️  Extra Cached Models ({len(extra_cached)}):")
    for model in sorted(extra_cached):
        print(f"  - {model}.py")
    print()

# Summary
if missing_cached:
    print(f"❌ Mapping Status: {len(cached_models)}/{len(fmp_models)} complete")
else:
    print("✅ Mapping Status: Perfect 1:1 mapping achieved!")

print("\n=== Model List Comparison ===")
print(f"FMP Models ({len(fmp_models)}):")
for model in sorted(fmp_models):
    status = "✅" if model in cached_models else "❌"
    print(f"  {status} {model}.py")