"""Post-session reporting + replay tools (Phase 5).

Nothing in this package is [agent]-gated — pure deterministic post-
processing of on-disk NDJSON journals. The [xlsxwriter] extra is
optional and only affects the XLSX renderer (xlsx_builder.py); the MD +
JSON paths work with the core install alone.
"""
