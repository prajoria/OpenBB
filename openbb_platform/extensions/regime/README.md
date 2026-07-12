# openbb-regime

Shared market-regime detector for OpenBB (Analysis + techtrade consumers).

## Purpose

Classifies the current market state into one of four regimes so downstream
consumers (Analysis P7 composite scoring, techtrade signal weighting,
future risk-parity allocator) can adapt behavior:

- `TRENDING_BULL` — SPY above 200d MA + low VIX, favor trend-following signals
- `RANGING` — SPY around 200d MA + moderate VIX, favor mean-reversion signals
- `TRENDING_BEAR` — SPY below 200d MA + rising VIX, defensive positioning
- `CRISIS` — SPY well below 200d MA + VIX spike (>30), zero-out risk

## Design invariants

- **Hysteresis**: regime must persist for 3 consecutive trading days before a
  switch is emitted (prevents whipsaw at threshold boundaries)
- **Golden fixtures**: Mar 2020 (COVID) → `CRISIS`, Nov 2020 (post-election) →
  `TRENDING_BULL`. These are load-bearing regression anchors.
- **Shared, not embedded**: this is a standalone extension (per Q-1 design
  decision) so both Analysis and techtrade consume the same signal — no
  duplicated regime logic.

## Consumers

- **Analysis** (`Analysis/stock_analysis.py`): Phase 7 composite weight
  adjustment + `staged_entry` tranche scaling (bd-0h2.14, bd-0h2.15)
- **techtrade** (future): signal-preset selection (`trend_follow` in
  `TRENDING_BULL`, `mean_revert` in `RANGING`, disable in `CRISIS`)

See `docs/superpowers/specs/analysis-pipeline-hardening-plan.md` §Phase B.
