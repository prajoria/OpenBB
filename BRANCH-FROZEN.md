# 🔒 BRANCH FROZEN — feat/93-openfigi-ticker-cusip-resolver

> **Do not commit further work to this branch.** Implementation is complete and
> awaiting review on **[PR #95](https://github.com/prajoria/OpenBB/pull/95)**.

## What's done

Closes [#93](https://github.com/prajoria/OpenBB/issues/93). 5 commits delivering
the broad ticker→CUSIP resolver via OpenFIGI `/v3/mapping`:

| SHA | Message |
|---|---|
| `45425ec97` | `feat(sec/93): OpenFIGI /v3/mapping client + openfigi_map_cache read-through` |
| `1c5df16fc` | `feat(tools/93): enrich_cusip_figi.py -- broad OpenFIGI ticker→CUSIP backfill` |
| `d7b5365c7` | `docs(tools/93): per-tool spec + DESIGN.md inventory for enrich_cusip_figi` |
| `a5b05645b` | `test(93): end-to-end verification -- bounded OpenFIGI live run` |
| `9e8ed5670` | `docs(93): design doc — broad ticker→CUSIP resolver via OpenFIGI` |

All four bead tasks (`OpenBBTechnical-z2t / -ofg / -86t / -8rt`) are closed.
51/51 #93-related unit tests pass; live `--limit 100 --max-batches 2` run is
recorded in `Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md`.

## Rules while this marker exists

- **No new commits** on `feat/93-openfigi-ticker-cusip-resolver`.
- **No force-pushes** that rewrite the 5 commits above (it would invalidate
  PR #95's review history).
- **Review feedback on PR #95:** address it on a **new** branch off
  `feat/93-...`, then either rebase or land via a follow-up PR — discuss
  approach with the reviewer first. Do not amend in place.
- **If you need to keep working on the same feature area** (e.g. a #93
  follow-up like R7's FIGI-refresh job): branch off `trading_technicals`
  *after* this PR merges, not off this branch.

## Unfreeze conditions

Delete this file (and the freeze banner in
`docs/superpowers/plans/2026-06-25-93-openfigi-ticker-cusip-resolver.md`) only
when **one** of the following is true:

1. PR #95 has merged → the marker can be removed in a separate small commit on
   `trading_technicals`, optionally as part of the merge commit.
2. PR #95 has been formally closed without merging → branch is being abandoned
   or retired; mark this file with a CLOSED reason before deleting.

## Pointers

- **PR:** https://github.com/prajoria/OpenBB/pull/95
- **Issue:** https://github.com/prajoria/OpenBB/issues/93
- **Design doc:** [`docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md`](docs/designs/quant_trading/93-openfigi-ticker-cusip-resolver.md)
- **Plan:** [`docs/superpowers/plans/2026-06-25-93-openfigi-ticker-cusip-resolver.md`](docs/superpowers/plans/2026-06-25-93-openfigi-ticker-cusip-resolver.md)
- **Live-run evidence:** [`Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md`](Tools/docs/runs/2026-06-25-enrich-cusip-figi-bounded.md)
- **Beads:** parent `OpenBBTechnical-cse` (un-deferred); children `z2t / ofg / 86t / 8rt` (closed)
