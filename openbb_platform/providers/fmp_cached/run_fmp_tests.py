#!/usr/bin/env python3
"""
VS Code Test Runner for FMP Cached Provider

This script provides a convenient way to run tests for the FMP cached provider
with proper environment setup and filtering.
"""

import os
import sys
import subprocess
from pathlib import Path

# Add the project root to Python path
FMP_CACHED_DIR = Path(__file__).parent
PROJECT_ROOT = FMP_CACHED_DIR.parent.parent.parent
sys.path.insert(0, str(PROJECT_ROOT))
sys.path.insert(0, str(PROJECT_ROOT / "openbb_platform" / "core"))
sys.path.insert(0, str(FMP_CACHED_DIR))

def run_tests(test_pattern="", verbose=True, test_mode=True, include_slow=False):
    """Run FMP cached provider tests with proper configuration."""
    
    # Set up environment
    env = os.environ.copy()
    if test_mode:
        env["FMP_CACHE_TEST_MODE"] = "true"
    
    # Base pytest command
    cmd = [
        sys.executable, "-m", "pytest",
        str(FMP_CACHED_DIR / "tests"),
    ]
    
    # Add test pattern if specified
    if test_pattern:
        cmd.extend(["-k", test_pattern])
    
    # Add options
    if verbose:
        cmd.append("-v")
    
    cmd.extend(["--tb=short", "--color=yes"])
    
    if include_slow:
        cmd.append("--runslow")
    
    # Add specific tests that work (avoid broken imports)
    working_tests = [
        "test_database_config.py",
        "test_equity_historical_cached.py", 
        "test_fmp_cached_fetchers.py",
        "test_performance.py",
        "test_real_integration.py",
        "test_simple_integration.py",
        "test_with_user_settings.py"
    ]
    
    print("🧪 Running FMP Cached Provider Tests")
    print("=" * 50)
    print(f"Environment: {'Test Mode' if test_mode else 'Production Mode'}")
    print(f"Command: {' '.join(cmd)}")
    print(f"Working Directory: {PROJECT_ROOT}")
    print()
    
    # Run tests
    try:
        result = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
        return result.returncode
    except KeyboardInterrupt:
        print("\n❌ Tests interrupted by user")
        return 1
    except Exception as e:
        print(f"❌ Error running tests: {e}")
        return 1

def main():
    """Main entry point for test runner."""
    import argparse
    
    parser = argparse.ArgumentParser(description="Run FMP cached provider tests")
    parser.add_argument("-k", "--pattern", help="Test pattern to match")
    parser.add_argument("-q", "--quiet", action="store_true", help="Less verbose output")
    parser.add_argument("--prod", action="store_true", help="Use production database")
    parser.add_argument("--slow", action="store_true", help="Include slow tests")
    
    args = parser.parse_args()
    
    return run_tests(
        test_pattern=args.pattern,
        verbose=not args.quiet,
        test_mode=not args.prod,
        include_slow=args.slow
    )

if __name__ == "__main__":
    sys.exit(main())