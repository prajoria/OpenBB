"""Common enums used across FinancialToolkit domain routers."""

from enum import Enum


class CoverageStatus(str, Enum):
    """Coverage status for command-to-toolkit mapping."""

    planned = "planned"
    scaffolded = "scaffolded"
    implemented = "implemented"
