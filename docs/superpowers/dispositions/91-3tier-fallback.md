# Disposition — GH Epic #91: 3-tier FMP/CBOE Historical-Data Fallback

**Decision:** DROP
**Author:** Trading Automation working group (via Phase 0 Task 7)
**Date:** 2026-07-08
**Refs:** [`docs/superpowers/plans/2026-07-06-fmp-trading-phase0.md`](../plans/2026-07-06-fmp-trading-phase0.md) Task 7 · [GH Epic #91](https://github.com/prajoria/OpenBB/issues/91) · fmp-day-trading PRD [`docs/superpowers/specs/2026-07-06-fmp-day-trading-automation-design.md`](../specs/2026-07-06-fmp-day-trading-automation-design.md) §1.1

---

## What #91 Is

GitHub epic #91 tracks approximately **1088 lines of Python** implementing a 3-tier historical-data fallback chain: `fmp_cached → fmp → cboe`. It targets daily historical OHLCV data. The code was written in a prior generation of the fork, currently orphaned (not imported by any active module), and PRD §1.1 flagged it as a candidate for "repurpose as intraday 3-tier chain."

## The Question Phase 0 Was Asked

Two viable paths:
1. **Port** — adapt the 1088-LoC fallback into `openbb_fmp_cached/models/base_cached.py` as a reusable primitive for later phases (particularly Phase 2's tier-1 caching + the eventual CBOE-options-context path).
2. **Drop** — leave the code orphaned, document why here, focus intraday-specific caching effort in Phase 2 without inheriting the shape of the historical-data fallback.

## Decision: DROP

The disposition doc is the audit trail. Rationale below in the order that weighed most.

### 1. The semantics don't map

The #91 fallback was written for **daily historical bars** with these implicit assumptions:
- Missing-bar means "the data doesn't exist" (weekend, holiday, delisted symbol, or provider gap)
- Fallback is *directional*: try the fastest tier, escalate to slower tiers when the fast one fails
- Freshness is per-request; there's no session concept

The intraday chain in the fmp-day-trading PRD has fundamentally different semantics:
- Missing-bar during trading hours means "cache is stale, fetch now" (the "tail bar might extend" rule from PRD §5.2 — mark `is_valid=FALSE`, re-fetch on the next tick)
- Fallback is *tier-aware and bandwidth-aware*, not just retry-on-failure — the `BandwidthMeter` (P6) can move the whole session into "conservation mode" or "halted" and change the fallback preference dynamically
- Freshness is session-scoped for extended-hours quotes (60s TTL for aftermarket-quote per PRD §5.2), not per-request

Porting the fallback would require reimplementing the whole session-awareness layer that #91's code doesn't have. Cheaper to write the intraday chain from scratch against Phase 2's actual requirements.

### 2. CBOE isn't in Phase 0-2 scope

The #91 fallback's third tier is **CBOE**, which the PRD explicitly defers:

> **NG4 — No options trading.** FMP has no options surface (research finding). Options *context* (IV/RV) can inform signals once cboe integration lands via Analysis Phase-D2, but options orders/positions are out of scope.

CBOE integration is on the Analysis Phase-D2 track (issues #279 / #280 / #281), which is not a blocking dependency for fmp-day-trading. Porting a 3-tier chain whose third tier is deliberately out of scope until v2+ means porting infrastructure with no consumer.

### 3. Battle-tested for the wrong shape

The strongest argument for porting is "the code is battle-tested." That's true for **the shape it was tested against** — daily historical bars, retry-on-failure semantics, no bandwidth accounting, no session lifecycle. Bringing that shape into the intraday chain would either (a) require rewriting internals until only the file-boundary remains, or (b) leak wrong-shape assumptions into Phase 2's tier-1 caching. Both are more work than writing fresh code against the actual requirements.

The `openbb_fmp_cached.models.equity_historical` module (which Phase 2 P2.1 mirrors for intraday bars) is a purpose-built tier-1 gap-detection cacher — a much better structural model for what Phase 2 needs than the #91 fallback chain.

### 4. Sunk-cost anti-pattern

Deciding to port because "the code exists" is the sunk-cost fallacy. The code cost the same to write whether we use it or not. What matters now is the marginal cost of shipping intraday caching with vs. without it. That comparison favors DROP.

## Consequences

- **#91 stays open** with a comment linking to this disposition. Anyone who lands here in six months sees the reasoning without having to reconstruct it.
- **Phase 2's intraday caching (P2.1, P2.2)** is written fresh against `equity_historical.py`'s pattern, not `#91`'s fallback chain.
- **If CBOE integration lands via Analysis Phase-D2**, that team can independently evaluate whether `#91`'s CBOE tier is worth reviving *for CBOE specifically*. Its historical-data shape may fit CBOE's options-context data better than it fits intraday equity bars.
- **The 1088 LoC on the `prajoria/FinanceToolkit` fork** stays orphaned. No effort to delete it. If it ever needs resurrection, it's still in git history and this doc explains why we skipped it once.

## What This Does NOT Foreclose

- **Fmp-trading v2 revisiting the decision.** If Phase 2's intraday cache proves fragile in ways that #91's chain solved for historical data, we can port selectively later. Nothing about this disposition is irreversible.
- **Reusing individual functions or ideas.** If a specific helper (e.g. a resilient HTTP-retry pattern) from #91 turns out to be genuinely useful, it can be lifted in isolation — the disposition is against wholesale porting, not against learning from the code.
- **Documenting the code's existence.** This disposition doc IS that documentation, in effect.

## Acceptance for Phase 0 Task 7

- [x] Disposition decision made (DROP)
- [x] Rationale documented in this file
- [x] #91 epic can now be closed with a comment linking here (do this in Task 8 rollup, not here — Task 8 owns the close-out actions)
- [x] No new code shipped by this task

---

*This is a decision record, not a proposal. If circumstances change, add a new disposition entry below rather than editing this one — the audit trail's value is in its immutability.*
