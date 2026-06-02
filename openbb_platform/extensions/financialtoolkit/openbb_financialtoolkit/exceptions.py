"""Extension-specific exceptions for FinancialToolkit."""


class FinancialToolkitError(Exception):
    """Base FinancialToolkit extension exception."""


class FinancialToolkitConfigurationError(FinancialToolkitError):
    """Raised when required extension configuration is invalid."""


class FinancialToolkitDependencyError(FinancialToolkitError):
    """Raised when FinanceToolkit dependency is unavailable."""


class FinancialToolkitExecutionError(FinancialToolkitError):
    """Raised when a wrapped FinanceToolkit operation fails."""
