"""Pytest configuration for FinancialToolkit extension tests."""

from pathlib import Path
import sys


EXTENSION_ROOT = Path(__file__).resolve().parents[1]

if str(EXTENSION_ROOT) not in sys.path:
    sys.path.insert(0, str(EXTENSION_ROOT))
