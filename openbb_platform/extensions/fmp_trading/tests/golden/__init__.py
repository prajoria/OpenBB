"""Golden tests for fmp_trading.

These lock architectural invariants (no look-ahead, chokepoint enforcement,
determinism under replay) at the tick-loop level. They differ from unit
tests in that they exercise real class collaboration — IntradaySession +
run_tick + typed events — with only external I/O stubbed.
"""
