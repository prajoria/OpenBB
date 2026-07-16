"""``tune`` sub-router: obb.techtrade.tune(segment, ...) (#83 L7, L5, L2, Q-A, Q-F, §5.3 W2).

The orchestration layer that wires T2/T3/T4 + #82's validate_plan together:

1. :func:`tuning.sector_ohlcv.pool_sector_ohlcv` -> ``(X, y)`` (L4 + Q-B + Q-C).
2. :func:`tuning.tuneta_adapter.fit_segment` -> ``(candidate IndicatorConfig,
   meta)`` (L6 + Q-D + Q-G).
3. :func:`_build_sample_plan` constructs a single-symbol TradePlan for the
   segment's benchmark ETF (Q-A A1 -- XLK for IT, XLF for Financials, ...).
4. **`with tune_override({segment: candidate}):`** (§5.3 W2) -- make the
   candidate visible to the validate fold loop without writing to disk first.
5. :func:`openbb_techtrade.validation.backtest_bridge.validate_plan` -> verdict.
6. If ``verdict == "robust"`` AND ``candidate != DEFAULT_CONFIG`` (Q-F guard 3
   no-op): :func:`tuning.tuned_defaults.write_tuned` persists. Otherwise the
   :class:`TuningReport` carries ``persisted=False`` and a diagnostic reason
   (Q-F transparent non-persist).
7. Return ``OBBject[TuningReport]``.

Note: this module deliberately does **not** use ``from __future__ import
annotations``. The ``tune`` command takes a ``segment: str`` (simple),
but the package builder still needs to see the real :class:`TradePlan` and
:class:`TuningReport` classes -- mirroring the
:mod:`openbb_techtrade.validation.validate_router` convention.
"""

import logging
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_techtrade.engine.indicators import DEFAULT_CONFIG, IndicatorConfig
from openbb_techtrade.models import (
    EntryExitRule,
    MoverSignal,
    Recommendation,
    TradePlan,
    TuningReport,
)
from openbb_techtrade.tuning.sector_ohlcv import (
    DEFAULT_FORWARD_HORIZON_BARS,
    DEFAULT_HORIZON_YEARS,
    pool_sector_ohlcv,
)
from openbb_techtrade.tuning.tuned_defaults import tune_override, write_tuned
from openbb_techtrade.tuning.tuneta_adapter import _require_tuneta, fit_segment
from openbb_techtrade.validation.backtest_bridge import validate_plan

logger = logging.getLogger(__name__)

#: Q-A A1: the sector ETF used as the sample-plan symbol for the per-segment validate.
#: Sourced from the 11 GICS Select Sector SPDRs (long-stable, liquid, deterministic).
SEGMENT_BENCHMARK_ETFS: dict[str, str] = {
    "Communication Services": "XLC",
    "Consumer Discretionary": "XLY",
    "Consumer Staples":       "XLP",
    "Energy":                 "XLE",
    "Financials":             "XLF",
    "Health Care":            "XLV",
    "Industrials":            "XLI",
    "Information Technology": "XLK",
    "Materials":              "XLB",
    "Real Estate":            "XLRE",
    "Utilities":              "XLU",
}


router = Router(prefix="", description="Per-segment indicator-period tuning gated by validation.")


def _build_sample_plan(segment: str, as_of: date) -> TradePlan:
    """Construct a deterministic single-symbol TradePlan for the segment's ETF (Q-A A1).

    validate_plan only reads ``symbol`` + ``as_of`` + ``rule.entry_threshold`` from
    the plan (#82 design §3.2 -- orders / fills / recommendation fields are
    attach targets, not validation inputs). The fixture below satisfies the
    input contract with deterministic zeroed values.
    """
    if segment not in SEGMENT_BENCHMARK_ETFS:
        raise ValueError(
            f"unknown segment {segment!r}; valid: {sorted(SEGMENT_BENCHMARK_ETFS)}"
        )
    etf = SEGMENT_BENCHMARK_ETFS[segment]
    sig = MoverSignal(
        symbol=etf, segment=segment, as_of=as_of,
        score=0.5, direction="long", votes=[], rank_in_segment=1,
    )
    rec = Recommendation(
        symbol=etf, segment=segment, as_of=as_of,
        action="BUY", conviction="Medium", score=0.5,
        entry_price=Decimal("100.00"), stop_price=Decimal("98.00"),
        target_price=Decimal("104.00"),
        stop_distance_pct=0.02, target_distance_pct=0.04,
        risk_reward=2.0, atr=2.0,
        position_size=Decimal("1"), risk_per_share=Decimal("2.00"),
        risk_pct_of_notional=0.0, time_stop_bars=20,
        reasoning="", top_factors=[], caveats="Tuneta sample plan (Q-A A1).",
    )
    return TradePlan(
        symbol=etf, segment=segment, as_of=as_of,
        signal=sig, rule=EntryExitRule(),
        position_size=Decimal("1"), orders=[], simulated_fills=[],
        recommendation=rec,
    )


def _reason_for(verdict: str, report: Any, *, no_op: bool) -> str:
    """Build the human-stable reason string (Q-F + Q-F guard 4 stable shape)."""
    if no_op:
        return "no change from defaults"
    pbo = getattr(report, "pbo", float("nan"))
    dsr = getattr(report, "deflated_sharpe", float("nan"))
    # Stable field order + 2-decimal precision so two runs produce identical strings.
    return f"verdict={verdict} (pbo={pbo:.2f}, dsr={dsr:.2f})"


@router.command(
    methods=["POST"],
    examples=[
        APIEx(
            description="Tune Information Technology with defaults.",
            parameters={"segment": "Information Technology"},
        ),
        APIEx(
            description="Tune Financials over 3 years with 50 trials.",
            parameters={
                "segment": "Financials",
                "horizon_years": 3,
                "trials": 50,
            },
        ),
    ],
)
async def tune(
    segment: str,
    *,
    as_of: date | None = None,
    horizon_years: int = DEFAULT_HORIZON_YEARS,
    forward_horizon_bars: int = DEFAULT_FORWARD_HORIZON_BARS,
    trials: int = 100,
    early_stop: int = 20,
    method: str = "wfo",
    thresholds: dict[str, float] | None = None,
    provider: str | None = None,
) -> OBBject:
    """Tune indicator periods for a GICS segment, gated by #82's validate (PRD §12.4, §15).

    Steps (design §4.1):

    1. Pool the segment's universe OHLCV into ``(X, y)`` (L4 + Q-C horizon
       window + Q-B forward-return target).
    2. Fit tuneta over the L6 8-knob search space -> candidate IndicatorConfig.
    3. Build a sample TradePlan for the segment's benchmark ETF (Q-A A1).
    4. ``with tune_override({segment: candidate}):`` make the candidate
       visible to the validate fold loop without writing to disk first
       (§5.3 W2 -- safe because #82's fold loop is sequential in-thread).
    5. ``validate_plan(plan, method=method, thresholds=thresholds,
       horizon_years=horizon_years, provider=provider)`` -> verdict.
    6. Gate: if verdict == "robust" AND the candidate genuinely differs from
       DEFAULT_CONFIG (Q-F guard 3) -> persist via write_tuned. Otherwise
       persisted=False + a diagnostic reason string. Logged at WARNING on
       fragile/overfit so a long loop is visible without an exception.
    7. Return OBBject[TuningReport].

    Raises
    ------
    TechtradeDependencyError
        When ``tuneta`` is not installed (raised by fit_segment via
        :func:`_require_tuneta`); or when ``openbb-backtest`` is not installed
        (raised by validate_plan via #82's ``_require_backtest``). The error
        message names the specific extra; for a full tune the user needs both
        ``[tuneta]`` and ``[validation]``.
    ValueError
        If ``segment`` is not one of the 11 GICS sectors in
        :data:`SEGMENT_BENCHMARK_ETFS` (Q-A A1).
    """
    effective_as_of = as_of if as_of is not None else date.today()
    # Fail-fast on the [tuneta] extra BEFORE any I/O (universe / OHLCV fetch).
    # Without this guard, an absent-tuneta install would surface as the first
    # downstream error -- often a provider/credentials failure -- masking the
    # real cause. Mirrors #82's _require_backtest() shape; both extras get the
    # same "early, explicit, actionable" treatment.
    _require_tuneta()
    plan = _build_sample_plan(segment, effective_as_of)

    X, y = pool_sector_ohlcv(
        segment,
        as_of=effective_as_of,
        horizon_years=horizon_years,
        forward_horizon_bars=forward_horizon_bars,
    )
    candidate, meta = fit_segment(X, y, trials=trials, early_stop=early_stop)

    with tune_override({segment: candidate}):
        _updated_plan, report = await validate_plan(
            plan,
            method=method, thresholds=thresholds,
            horizon_years=horizon_years, provider=provider,
        )

    verdict = getattr(report, "verdict", "unknown")
    no_op = candidate == DEFAULT_CONFIG
    persisted = False
    if verdict == "robust" and not no_op:
        write_tuned(
            segment, candidate,
            meta={
                "verdict": verdict,
                "pbo": getattr(report, "pbo", None),
                "dsr": getattr(report, "deflated_sharpe", None),
                "oos_sharpe": getattr(
                    getattr(report, "oos_metrics", None), "sharpe", None
                ),
                "tuned_at": datetime.now(timezone.utc).isoformat(timespec="seconds")
                            .replace("+00:00", "Z"),
                "tuneta_version": meta["tuneta_version"],
                "as_of": effective_as_of.isoformat(),
                "horizon_years": horizon_years,
            },
        )
        persisted = True
    elif verdict == "robust" and no_op:
        logger.info(
            "tune: segment %s verdict=robust but candidate == DEFAULT_CONFIG -> not persisted (no change)",
            segment,
        )
    elif verdict != "robust":
        logger.warning(
            "tune: segment %s verdict=%s -> not persisted (pbo=%s dsr=%s)",
            segment, verdict,
            getattr(report, "pbo", None),
            getattr(report, "deflated_sharpe", None),
        )

    return OBBject(results=TuningReport(
        segment=segment,
        as_of=effective_as_of,
        candidate=candidate,
        persisted=persisted,
        reason=_reason_for(verdict, report, no_op=no_op),
        tuneta_version=meta["tuneta_version"],
        fit_seconds=meta["fit_seconds"],
        trials=trials,
        early_stop=early_stop,
    ).model_copy(update={"validation": report}))  # attach via model_copy to mirror #82 bridge
    # (TuningReport.validation is typed Data|None to keep techtrade installable without
    # openbb-backtest; constructor would reject a SimpleNamespace fake, but model_copy
    # bypasses validation -- matching backtest_bridge.validate_plan line ~240.)
