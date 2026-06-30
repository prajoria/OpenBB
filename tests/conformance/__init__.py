"""Conformance harness package marker.

Per PRD section 7: every builtin / language feature has a paired
``<name>.pine`` source + ``<name>.csv`` reference output under this
directory. The pytest fixture in :mod:`conftest` discovers them all
automatically; a new builtin = two new files, no test code change.
"""
