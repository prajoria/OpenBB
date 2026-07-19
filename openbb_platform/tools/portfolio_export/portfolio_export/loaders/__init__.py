"""portfolio_export.loaders — broker-specific CSV → DataFrame parsers.

Each loader takes a file path and returns a typed pandas DataFrame.
Loaders NEVER print or log row content — only the DataFrame itself
carries the data, and downstream code decides what to display.
"""
