"""Test helpers shared between conformance harness and Tools/pine.

This subpackage exists so both the pytest harness (conftest.py) and
standalone CLIs under Tools/pine/ can share exactly the same canonical
serialization code — drift between capture-time and test-time is the
one thing that would silently invalidate the hybrid-fixture-suite
design's bars-hash gate.

See docs/superpowers/specs/2026-07-20-pine-hybrid-fixture-suite-design.md
§5 for the byte-exact serialization contract.
"""
