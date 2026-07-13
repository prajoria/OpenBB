# openbb-portfolio-intel

First-party OpenBB Platform extension delivering portfolio-level intelligence:
X-Ray look-through, Event Calendar, Smart-Money overlay, Risk decomposition,
Brinson attribution, What-If simulator, Paper Trading, and Alerts.

Sits on top of the `fmp_cached` provider and the `portfolio_app` service.

## Status

**M0 (scaffold-only)** — this extension currently exposes a single health-check
command, `obb.portfolio_intel.about()`. Full command surface lands in P1–P3
per the [Execution Plan](../../../docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md).

> **Namespace note:** commands live under `obb.portfolio_intel.*` (underscore),
> matching the `openbb_core_extension` entry-point key. OpenBB's plugin loader
> does not dot-split entry-point keys — see the sibling `openbb-backtest`
> extension whose entry-point `backtest` maps to `obb.backtest.*`. Nesting
> under `obb.portfolio.*` would collide with `openbb-portfolio-custom`.

## Docs

- **PRD:** [`docs/Specs/Portfolio-Intelligence-Engine-PRD.md`](../../../docs/Specs/Portfolio-Intelligence-Engine-PRD.md)
- **Execution Plan:** [`docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md`](../../../docs/Specs/Portfolio-Intelligence-Engine-Execution-Plan.md)
- **Bead epic:** `OpenBBTechnical-qy83`

## Install (dev)

```bash
cd openbb_platform && python dev_install.py -e
```

## License

AGPL-3.0-only, inherited from the fork.
