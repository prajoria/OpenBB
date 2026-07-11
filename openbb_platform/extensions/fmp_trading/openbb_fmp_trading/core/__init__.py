"""fmp_trading core: RiskManager, SessionJournal, BandwidthMeter, doctor.

The core package houses the deterministic session-side machinery that runs
inside IntradaySession (Phase 2). Nothing here does I/O to FMP directly —
data fetching stays in the providers; the core consumes typed TickData /
JournalEvent objects.
"""
