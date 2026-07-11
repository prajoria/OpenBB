"""Architecture-level tests for openbb-fmp-trading.

These enforce invariants that live at the codebase level rather than any
single function: chokepoint uniqueness (Phase 2 P2.4), core-unchanged-
when-extra-removed (Phase 3 P3.3), no broker leaks on the MCP surface
(Phase 3 P3.3).
"""
