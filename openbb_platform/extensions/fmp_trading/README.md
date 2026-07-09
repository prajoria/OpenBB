# openbb-fmp-trading

Intraday day-trading automation extension for the OpenBB Platform.

Ships a deterministic execution core with optional agent-driven pre-open discovery
and post-close review. Composes on `openbb-techtrade` unchanged; talks only to
`fmp_cached` (never raw `fmp` in application code).

Status: **Phase 1 — Foundations** (scaffold, models, RiskManager, Journal,
BandwidthMeter, doctor). See `docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`
for the full PRD.

Journal + replay use the shared `openbb-core-journal` primitive (`openbb_platform/core/openbb_core_journal/`, epic #408) — no local SessionJournal module in this extension.
