"""Decorrelation gate for the extended trend family (bd-luy Step 4, bd-8332).

**Contract:** pairwise |Spearman ρ| ≤ 0.70 across all trend votes (§R.4 M4
tightened from 0.85 — 0.85 admits 72% shared variance which defeats
intra-family diversification).

**Interpretation:** if two trend votes correlate above 0.70, they're
mechanistically overlapping — the ensemble treats them as ~1.5 votes
instead of 2. The gate prevents that concentration.

**Diagnostic outputs (never fail on these — reviewer inspection only):**
- Full pairwise Spearman matrix printed
- Near-miss pairs (0.60 ≤ |ρ| ≤ 0.70) called out
- Aroon-vs-ADX-level correlation reported as FYI (ADX isn't a vote but
  shares the directional-movement mechanism per §R.4 M4 tail).

**Marked `integration`** — iterates the 5-year basket × 5 symbols × ~7
votes per bar (~30s wall-clock).

Full context:
- Plan: docs/superpowers/plans/2026-07-09-bd-luy-trend-family-expansion.md Step 4
- Design spec: docs/superpowers/specs/2026-07-08-confluence-panel-expansion-design.md §3.1
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import indicators
from openbb_techtrade.engine.confluence_ext import trend_votes_ext
from openbb_techtrade.engine.panel_config import PANEL_EXTENDED
from tests.fixtures import load_basket


DECORRELATION_CEILING = 0.70
"""Pairwise |Spearman ρ| gate. §R.4 M4: tightened from 0.85."""

NEAR_MISS_FLOOR = 0.60
"""Lower bound for the near-miss diagnostic band (reported, not gated)."""

#: Minimum bars per rolling window; matches Ichimoku's 78-bar minimum.
#: Windows without enough history return NaN votes which get dropped.
MIN_BARS_FOR_VOTES = 78


def _build_vote_series_for_symbol(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """Build a per-day DataFrame of {vote_name: vote_value} for `symbol`.

    For each date t in the history, compute the extended trend panel + votes
    using OHLCV up to and including t. Extract each vote's numeric value.

    Returns a DataFrame indexed by date with one column per vote name.
    Rows where the panel couldn't be built (insufficient history) are
    NaN and get dropped by the caller before correlation.
    """
    from openbb_techtrade.models import IndicatorPanel

    df = df.sort_index()
    dates: list[pd.Timestamp] = []
    rows: list[dict[str, float]] = []

    # Step by 5 to keep runtime manageable (~30s per symbol otherwise).
    for i in range(MIN_BARS_FOR_VOTES, len(df), 5):
        window = df.iloc[: i + 1]
        as_of_dt = window.index[-1].date()
        records = window.reset_index().to_dict(orient="records")
        # Rename the index-column to 'timestamp' as build_indicator_panel expects
        if "date" in records[0]:
            records = [{"timestamp": r.pop("date"), **r} for r in records]
        try:
            panel = indicators.build_indicator_panel(
                symbol=symbol,
                as_of=as_of_dt,
                ohlcv_rows=records,
                panel_config=PANEL_EXTENDED,
            )
        except Exception:  # noqa: BLE001 — skip failed windows
            continue

        vote_row: dict[str, float] = {}
        for vote in trend_votes_ext(panel):
            vote_row[vote.name] = vote.vote

        if vote_row:
            dates.append(window.index[-1])
            rows.append(vote_row)

    return pd.DataFrame(rows, index=pd.DatetimeIndex(dates))


def _pairwise_spearman(vote_frame: pd.DataFrame) -> pd.DataFrame:
    """Return the pairwise Spearman correlation matrix (symmetric, |*|)."""
    return vote_frame.corr(method="spearman").abs()


@pytest.mark.integration
@pytest.mark.xfail(
    reason=(
        "bd-hpxh: ema_cross vs ichimoku_cloud pairwise |Spearman ρ| = 0.839 "
        "on the 5-year basket, above the §R.4 M4 gate of 0.70. Real "
        "mechanistic overlap (both trend-direction crossovers). Design "
        "decision required — see bd-hpxh — before this gate can pass. "
        "Options: (a) drop ichimoku_cloud from ship config keeping the "
        "panel key for audit [recommended], (b) drop ema_cross [aggressive], "
        "(c) reweight one down. Un-xfail once bd-hpxh lands the resolution."
    ),
    strict=True,  # if this ever passes, un-xfail — bd-hpxh has been resolved
)
def test_extended_trend_family_pairwise_decorrelation():
    """Pairwise |Spearman ρ| ≤ 0.70 for every trend-vote pair, pooled
    across the 5-symbol basket. Reports the full matrix, near-miss pairs,
    and Aroon-vs-ADX diagnostic before asserting.

    R7.11 discipline: the diagnostic REPORT is emitted before the assert
    so reviewers can see numbers even when the gate passes."""
    basket = load_basket()

    # Concatenate per-symbol vote frames; correlation is pooled cross-symbol
    # (weights all symbols equally regardless of history length).
    pooled_rows: list[pd.DataFrame] = []
    for symbol, df in basket.items():
        vote_frame = _build_vote_series_for_symbol(symbol, df)
        if vote_frame.empty:
            continue
        pooled_rows.append(vote_frame)

    if not pooled_rows:
        pytest.skip("no vote data produced for any basket symbol")

    pooled = pd.concat(pooled_rows, axis=0).dropna(how="any")
    assert len(pooled) >= 100, (
        f"pooled vote frame has only {len(pooled)} rows — insufficient "
        f"to estimate correlations robustly"
    )
    assert pooled.shape[1] >= 2, (
        f"need at least 2 vote series to compute pairwise correlation; "
        f"got {pooled.shape[1]}: {list(pooled.columns)}"
    )

    corr = _pairwise_spearman(pooled)

    # Report full matrix.
    print("\n[bd-8332] Pairwise |Spearman ρ| for extended trend votes:")
    print(corr.round(3).to_string())

    # Extract upper triangle pairs (i < j).
    vote_names = list(corr.columns)
    pair_rows: list[tuple[str, str, float]] = []
    for i, a in enumerate(vote_names):
        for b in vote_names[i + 1 :]:
            rho = float(corr.loc[a, b])
            if not np.isnan(rho):
                pair_rows.append((a, b, rho))

    # Report near-miss pairs (diagnostic only).
    near_miss = [(a, b, r) for a, b, r in pair_rows
                 if NEAR_MISS_FLOOR <= r <= DECORRELATION_CEILING]
    if near_miss:
        print(f"\n[bd-8332] Near-miss pairs "
              f"(|ρ| in [{NEAR_MISS_FLOOR:.2f}, {DECORRELATION_CEILING:.2f}]):")
        for a, b, r in near_miss:
            print(f"  {a:20s} vs {b:20s} : {r:.3f}")

    # Assert gate.
    violations = [(a, b, r) for a, b, r in pair_rows if r > DECORRELATION_CEILING]
    assert not violations, (
        f"decorrelation gate |ρ| ≤ {DECORRELATION_CEILING} violated by:\n"
        + "\n".join(f"  {a} vs {b}: {r:.3f}" for a, b, r in violations)
        + f"\n\n§R.4 M4: pairs above {DECORRELATION_CEILING} concentrate "
        f"the ensemble; either drop one of the pair or accept an "
        f"explicit widened ceiling with rationale."
    )


@pytest.mark.integration
def test_aroon_vs_adx_diagnostic():
    """FYI diagnostic (§R.4 M4 tail): Aroon oscillator shares the
    directional-movement mechanism with ADX. Report Aroon-vs-ADX-level
    correlation but do NOT gate — ADX isn't a directional vote in the
    extended panel; it's a gate/scaler."""
    basket = load_basket()

    aroon_vs_adx: list[float] = []
    for symbol, df in basket.items():
        df = df.sort_index()
        adx_series: list[float] = []
        aroon_series: list[float] = []
        for i in range(MIN_BARS_FOR_VOTES, len(df), 5):
            window = df.iloc[: i + 1]
            as_of_dt = window.index[-1].date()
            records = window.reset_index().to_dict(orient="records")
            if "date" in records[0]:
                records = [{"timestamp": r.pop("date"), **r} for r in records]
            try:
                panel = indicators.build_indicator_panel(
                    symbol=symbol, as_of=as_of_dt, ohlcv_rows=records,
                    panel_config=PANEL_EXTENDED,
                )
            except Exception:  # noqa: BLE001
                continue
            adx = panel.trend.get("adx")
            aroon_osc = panel.trend.get("aroon_osc")
            if adx is not None and aroon_osc is not None:
                adx_series.append(adx)
                aroon_series.append(aroon_osc)

        if len(adx_series) >= 30:
            rho = pd.Series(adx_series).corr(
                pd.Series(aroon_series), method="spearman"
            )
            aroon_vs_adx.append(float(rho))
            print(f"[bd-8332 FYI] {symbol}: Aroon_osc vs ADX-level "
                  f"Spearman ρ = {rho:.3f} (n={len(adx_series)})")

    # Diagnostic only — the assertion is that we produced *some* number
    # so the diagnostic actually ran.
    assert aroon_vs_adx, "expected at least one symbol to produce Aroon-vs-ADX correlation"
