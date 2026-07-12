"""Router for the shared market-regime extension (bd-0h2.16 / Phase B4).

Exposes ``obb.regime.detect()`` for downstream consumers (Analysis
pipeline, techtrade, portfolio_app, ad-hoc Workspace widgets) so
they can query a single canonical MarketRegime signal rather than
each re-implementing SPY-vs-200d + VIX classification.

REST surface
------------
* ``GET /api/v1/regime/detect`` — current regime as of today (or
  ``as_of`` if provided). Returns a JSON object with the enum name
  and a human-readable description.
* ``GET /api/v1/regime/about`` — metadata / documentation endpoint.

Python surface
--------------
* ``obb.regime.detect(as_of=...)`` — returns an :class:`OBBject` with
  ``results["regime"]`` set to the MarketRegime string value.

Design notes
------------
The router fetches SPY + VIX daily bars internally via ``obb.index.
price.historical`` (fmp / fmp_cached / yfinance provider) rather than
requiring the caller to supply DataFrames. This keeps the API simple
(one call → one regime) at the cost of hiding the data-fetch step.

The default lookback for SPY is 400 days (200-day SMA + margin for the
33-day walkback window). VIX is fetched over the same period.

For advanced use cases where the caller already has the data (e.g.
backtests), :func:`openbb_regime.detect_market_regime` is still
exported for direct import.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

from openbb_core.app.model.example import APIEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_regime.detector import MarketRegime, detect_market_regime

logger = logging.getLogger(__name__)


router = Router(
    prefix="",
    description="Shared market-regime detector (Analysis + techtrade consumers).",
)


# Fetch window defaults — 200d SMA + 33d walkback + margin for weekends/holidays.
_DEFAULT_FETCH_DAYS: int = 400
_DEFAULT_SPY_SYMBOL: str = "SPY"
_DEFAULT_VIX_SYMBOL: str = "^VIX"

# bd-6g5i (PR #470 I2): default provider to fmp_cached, matching the
# repo-wide Provider rule in CLAUDE.md's Analysis Module section. Every
# downstream consumer (Analysis P7 composite weights, techtrade panel-eval)
# assumes fmp_cached-shape responses; letting provider=None fall through
# to the platform default would silently pull a different provider on
# clones where the first-configured provider isn't fmp_cached, violating
# the invariant. Callers can still override explicitly for R&D use cases.
_DEFAULT_PROVIDER: str = "fmp_cached"


@router.command(
    methods=["GET"],
    include_in_schema=False,
    examples=[],
)
def about() -> OBBject:
    """Metadata endpoint — describes the regime router surface."""
    return OBBject(
        results={
            "name": "openbb-regime",
            "purpose": (
                "Shared MarketRegime detector for Analysis + techtrade " "consumers."
            ),
            "endpoints": {
                "detect": (
                    "GET /api/v1/regime/detect — classify current regime "
                    "from SPY + VIX daily bars"
                ),
                "about": "GET /api/v1/regime/about — this endpoint",
            },
            "regimes": [r.value for r in MarketRegime],
            "python": "from openbb import obb; obb.regime.detect()",
            "direct_import": (
                "from openbb_regime import detect_market_regime, " "MarketRegime"
            ),
        }
    )


@router.command(
    methods=["GET"],
    examples=[
        APIEx(
            description="Current market regime",
            parameters={},
        ),
        APIEx(
            description="Regime as of a historical date (backtesting)",
            parameters={"as_of": "2020-03-16"},
        ),
    ],
)
def detect(
    as_of: Optional[str] = None,
    lookback_days: int = _DEFAULT_FETCH_DAYS,
    spy_symbol: str = _DEFAULT_SPY_SYMBOL,
    vix_symbol: str = _DEFAULT_VIX_SYMBOL,
    provider: Optional[str] = _DEFAULT_PROVIDER,
) -> OBBject:
    """Detect the current MarketRegime from SPY + VIX daily bars.

    Parameters
    ----------
    as_of : str, optional
        ISO-format date (``YYYY-MM-DD``) to snap the classification to.
        Defaults to today. Useful for backtesting or auditing a
        historical regime call.
    lookback_days : int, default 400
        Days of daily bars to fetch. Must be >= 233 (200d SMA + 33d
        walkback window). Default 400 gives a comfortable margin over
        weekends and holidays.
    spy_symbol : str, default "SPY"
        Symbol for the broad market index. SPY is the standard.
    vix_symbol : str, default "^VIX"
        Symbol for the volatility index. The ``^VIX`` prefix works with
        yfinance / fmp_cached; users on other providers may need a
        different ticker convention.
    provider : str, optional
        OpenBB data provider. Defaults to ``"fmp_cached"`` (matches
        CLAUDE.md's Provider rule — see :data:`_DEFAULT_PROVIDER`).
        Callers can override explicitly for R&D use cases, but
        downstream Analysis + techtrade consumers assume fmp_cached
        response shapes.

    Returns
    -------
    OBBject
        Results object with ``results["regime"]`` = MarketRegime string
        value (e.g. ``"TRENDING_BULL"``), plus a diagnostic dict of
        the detector's inputs (as_of, spy_symbol, vix_symbol, provider).

    Notes
    -----
    * Fetches SPY + VIX via ``openbb.index.price.historical`` and
      ``openbb.equity.price.historical``. If neither call succeeds,
      returns ``MarketRegime.UNKNOWN`` with a WARNING (R7.3 loud empty).
    * The regime classification uses a 3-day hysteresis window with a
      33-day walkback fallback for whipsawing markets. See
      :func:`openbb_regime.detect_market_regime` for the algorithm.
    """
    # Lazy OpenBB import — keeps the extension import cycle clean.
    from openbb import obb

    # Compute the fetch window: as_of is the endpoint, lookback_days
    # back is the start.
    #
    # bd-ktzd (PR #470 I1): guard both call sites.
    #   1. datetime.utcnow() is deprecated on Py3.12+ (naive UTC); use
    #      datetime.now(tz=timezone.utc) — timezone-aware, forward-compat.
    #   2. datetime.fromisoformat(as_of) on untrusted REST query params
    #      raises ValueError on malformed input (e.g. ?as_of=today), which
    #      surfaces as a raw HTTP 500 instead of this file's structured
    #      _unknown_result diagnostic. Wrap in try/except and return the
    #      standard UNKNOWN result so the operator gets an actionable
    #      error message.
    if as_of is not None:
        try:
            end_dt = datetime.fromisoformat(as_of)
        except (ValueError, TypeError) as exc:
            logger.warning(
                "regime.detect: invalid as_of=%r (must be ISO-8601): %s — "
                "returning UNKNOWN with diagnostic",
                as_of,
                exc,
            )
            return _unknown_result(
                reason="invalid_as_of",
                as_of=as_of,
                error=f"as_of must be ISO-8601 (YYYY-MM-DD or YYYY-MM-DDTHH:MM:SS): {exc}",
                spy_symbol=spy_symbol,
                vix_symbol=vix_symbol,
            )
    else:
        end_dt = datetime.now(tz=timezone.utc)
    start_dt = end_dt - timedelta(days=lookback_days)
    start_iso = start_dt.date().isoformat()
    end_iso = end_dt.date().isoformat()

    fetch_kwargs = {"start_date": start_iso, "end_date": end_iso}
    if provider is not None:
        fetch_kwargs["provider"] = provider

    # Fetch SPY (equity.price.historical) and VIX (index.price.historical).
    # VIX is typically only available via the `index` router because
    # ^VIX is a CBOE index, not an equity.
    try:
        spy_result = obb.equity.price.historical(symbol=spy_symbol, **fetch_kwargs)
        spy_df = spy_result.to_df()
    except Exception as e:
        logger.warning(
            "regime.detect: SPY fetch failed (symbol=%s, provider=%s): %s "
            "— returning UNKNOWN",
            spy_symbol,
            provider,
            e,
        )
        return _unknown_result(
            reason="SPY fetch failed",
            as_of=as_of,
            error=str(e),
            spy_symbol=spy_symbol,
            vix_symbol=vix_symbol,
        )

    try:
        vix_result = obb.index.price.historical(symbol=vix_symbol, **fetch_kwargs)
        vix_df = vix_result.to_df()
    except Exception as e:
        logger.warning(
            "regime.detect: VIX fetch failed (symbol=%s, provider=%s): %s "
            "— returning UNKNOWN",
            vix_symbol,
            provider,
            e,
        )
        return _unknown_result(
            reason="VIX fetch failed",
            as_of=as_of,
            error=str(e),
            spy_symbol=spy_symbol,
            vix_symbol=vix_symbol,
        )

    # Run the classifier.
    # bd-6g5i (PR #470 I5): pass end_iso (validated date-ISO) instead of
    # raw as_of string. Even though as_of was validated above via
    # fromisoformat, closing the latent trap where a caller directly
    # constructs a call with malformed as_of that somehow bypasses the
    # guard (defense-in-depth). end_iso is guaranteed .isoformat() output.
    regime = detect_market_regime(spy_df, vix_df, as_of=end_iso)

    return OBBject(
        results={
            "regime": regime.value,
            "as_of": as_of if as_of else end_iso,
            "spy_symbol": spy_symbol,
            "vix_symbol": vix_symbol,
            "provider": provider,
            "lookback_days": lookback_days,
            "spy_rows": len(spy_df),
            "vix_rows": len(vix_df),
        }
    )


def _unknown_result(
    *,
    reason: str,
    as_of: Optional[str],
    error: str,
    spy_symbol: str,
    vix_symbol: str,
) -> OBBject:
    """Construct an UNKNOWN-regime OBBject with diagnostic info.

    R7.3 loud-empty: the caller can inspect ``results["reason"]`` +
    ``results["error"]`` to understand WHY the classification degraded
    to UNKNOWN, rather than being left with a bare "we don't know".
    """
    return OBBject(
        results={
            "regime": MarketRegime.UNKNOWN.value,
            "as_of": as_of,
            "reason": reason,
            "error": error,
            "spy_symbol": spy_symbol,
            "vix_symbol": vix_symbol,
        }
    )
