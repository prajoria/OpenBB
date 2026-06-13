# openbb-techtrade

Segment-aware technical-indicator trading engine for the OpenBB Platform.

Maps GICS sectors to universes, ranks top movers, computes a `pandas-ta-classic`
indicator panel, fuses indicators via weighted confluence voting into an explainable
signal, builds risk-based trade plans with paper-filled recommendations, exports a
multi-sheet Excel workbook, and (optionally) validates robustness via `openbb-backtest`.

Status: **scaffold** (issue #65). See `docs/Specs/TechnicalTrading-Engine-PRD.md` for the
full functional spec and `docs/superpowers/plans/` for the delivery roadmap.

Public surface (incremental): `obb.techtrade.segments / movers / signals / plan / scan /
orders / simulate / export / validate / tune`.
