"""Portfolio cache-warmer job definitions for the OpenBB jobs service (issue #1934).

Exposes two allowlisted, typed jobs discovered by the core jobs worker through the
``openbb_job_extension`` entry-point group:

- ``portfolio.position_history`` -- warms the ``equity_historical`` cache for
  Portfolio_Positions symbols (weekdays 01:00 local, ahead of market prep);
- ``portfolio.etf_holdings`` -- warms the ``etf_holdings`` cache for the 11 GICS
  sector SPDRs plus portfolio-held/extra ETFs (weekdays 02:00 local).

Both handlers wrap the structured, importable ``run_*_warm`` functions extracted
from the ``fetch_position_history`` and ``refresh_etf_holdings_cache`` CLIs onto a
core ``JobResult`` (bounded JSON-safe summary + warnings). Neither job's params nor
its result ever carries an API key or other credential -- provider credentials are
resolved internally (env / user_settings), exactly as the CLIs already do, and are
never threaded through job parameters or persisted in the job result. A partial
per-item failure (some symbols/ETFs error while others succeed) is surfaced as a
bounded warning so the job run is classified ``succeeded_with_warnings`` rather than
either silently "succeeded" or a hard "failed" -- consistent with the CLIs'
documented skip-and-continue behavior at item granularity.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from openbb_core.app.jobs.models import (
    MAX_WARNING_COUNT,
    MAX_WARNING_LENGTH,
    JobContext,
    JobDefinition,
    JobResult,
)
from openbb_core.app.jobs.schedules import DailySchedule
from pydantic import BaseModel, ConfigDict, Field

from portfolio_utils.fetch_position_history import run_position_history_warm
from portfolio_utils.refresh_etf_holdings_cache import run_etf_holdings_warm

#: Weekdays Monday-Friday (matches ``datetime.weekday()`` 0=Mon..4=Fri).
_TRADING_WEEKDAYS = (0, 1, 2, 3, 4)

#: Environment override for the schedule timezone; falls back to the market zone.
#: Shared name with ``openbb_techtrade.jobs`` so operators set one variable for
#: every pre-open cache/scan job in the deployment.
_TIMEZONE_ENV = "OPENBB_JOBS_TIMEZONE"
_DEFAULT_TIMEZONE = "America/New_York"


def _default_timezone() -> str:
    """Return the IANA timezone used for portfolio cache-warmer schedules.

    Honors ``OPENBB_JOBS_TIMEZONE`` when set, then the machine's local zone (via the
    optional ``tzlocal`` dependency), and finally the market's ``America/New_York`` --
    a sensible "local" for pre-open cache warming ahead of the XNYS session.
    """
    override = os.environ.get(_TIMEZONE_ENV)
    if override:
        return override

    try:  # pragma: no cover - depends on optional dependency availability
        from tzlocal import get_localzone_name

        local = get_localzone_name()
    except Exception:  # pragma: no cover - tzlocal missing or unresolved
        local = None
    if local:
        return local

    return _DEFAULT_TIMEZONE


def _bounded_warnings(messages: list[str]) -> list[str]:
    """Clamp warning count and per-message length to the JobResult limits."""
    return [message[:MAX_WARNING_LENGTH] for message in messages[:MAX_WARNING_COUNT]]


def _should_cancel(context: JobContext) -> Callable[[], bool]:
    """Return a cooperative cancellation check for ``context``'s run.

    The current worker seam does not surface a live per-run cancellation flag to
    running handlers (queued-run cancellation only; see
    ``openbb_core.app.jobs.models.JobRun.cancel``), so this always returns
    ``False`` today -- matching the same documented limitation noted in
    ``openbb_techtrade.jobs``. It is threaded through so ``run_position_history_warm``
    / ``run_etf_holdings_warm`` (and the item loops beneath them) already check
    cancellation between symbols/ETFs, and a future worker enhancement that starts
    surfacing a live signal via ``context`` only needs to change this one function.
    """

    def _check() -> bool:
        return False

    return _check


class PositionHistoryJobParams(BaseModel):
    """Parameters for ``portfolio.position_history``.

    Never includes an API key/credential -- the handler resolves the FMP
    credential internally (user settings, then ``FMP_API_KEY`` env var), exactly
    as the CLI does.
    """

    model_config = ConfigDict(extra="forbid")

    symbols: list[str] | None = Field(
        default=None,
        description="Explicit symbols to fetch; defaults to every Portfolio_Positions symbol.",
    )
    years: int = Field(
        default=5, ge=1, le=30, description="Years of daily history to warm."
    )
    skip_holiday_prestep: bool = Field(
        default=False, description="Skip the market_holidays pre-step (not recommended)."
    )


class EtfHoldingsJobParams(BaseModel):
    """Parameters for ``portfolio.etf_holdings``.

    Never includes an API key/credential -- the handler resolves the FMP
    credential internally (env var, then user_settings via the obb provider's own
    resolver), exactly as the CLI does.
    """

    model_config = ConfigDict(extra="forbid")

    etfs: list[str] | None = Field(
        default=None,
        description="Extra ETF tickers to refresh atop the SPDR + portfolio universe.",
    )
    skip_portfolio: bool = Field(
        default=False, description="Skip the Portfolio_Positions read; SPDRs + etfs only."
    )


def _run_position_history_job(
    context: JobContext, params: PositionHistoryJobParams
) -> JobResult:
    """Warm the equity_historical cache for portfolio symbols (handler)."""
    result = run_position_history_warm(
        symbols=params.symbols,
        years=params.years,
        dry_run=False,
        skip_holiday_prestep=params.skip_holiday_prestep,
        should_cancel=_should_cancel(context),
    )

    warnings = [f"{item['symbol']}: {item['error']}" for item in result.failed]
    if result.cancelled:
        warnings.append("run cancelled before all symbols were processed")

    return JobResult(summary=result.to_summary(), warnings=_bounded_warnings(warnings))


def _run_etf_holdings_job(context: JobContext, params: EtfHoldingsJobParams) -> JobResult:
    """Warm the etf_holdings cache for SPDRs + portfolio/extra ETFs (handler).

    ``api_key`` is intentionally left at its default (``None``): per
    ``refresh_etf_holdings_cache._resolve_api_key``'s own docstring the FMP
    credential is resolved by the ``obb.etf.holdings`` provider call itself
    from the process environment / user_settings, not threaded through this
    parameter -- so there is nothing for this handler to resolve or persist.
    """
    result = run_etf_holdings_warm(
        extra_etfs=params.etfs,
        skip_portfolio=params.skip_portfolio,
        dry_run=False,
        should_cancel=_should_cancel(context),
    )

    warnings: list[str] = []
    if result.errored:
        warnings.append(
            f"{result.errored} of {result.requested} ETF(s) failed to refresh "
            "(see worker logs for per-ETF errors)"
        )
    if result.cancelled:
        warnings.append("run cancelled before all ETFs were processed")

    return JobResult(summary=result.to_summary(), warnings=_bounded_warnings(warnings))


def get_job_definitions() -> list[JobDefinition]:
    """Return the portfolio cache-warmer job definitions for ``openbb_job_extension``."""
    timezone = _default_timezone()
    return [
        JobDefinition(
            name="portfolio.position_history",
            description=(
                "Warm the equity_historical cache for Portfolio_Positions symbols."
            ),
            params_model=PositionHistoryJobParams,
            handler=_run_position_history_job,
            schedule=DailySchedule(hour=1, minute=0, timezone=timezone, weekdays=_TRADING_WEEKDAYS),
            default_params={"years": 5, "skip_holiday_prestep": False},
            max_attempts=1,
            overlap_policy="forbid",
        ),
        JobDefinition(
            name="portfolio.etf_holdings",
            description=(
                "Warm the etf_holdings cache for the GICS sector SPDRs plus "
                "portfolio-held ETFs."
            ),
            params_model=EtfHoldingsJobParams,
            handler=_run_etf_holdings_job,
            schedule=DailySchedule(hour=2, minute=0, timezone=timezone, weekdays=_TRADING_WEEKDAYS),
            default_params={"skip_portfolio": False},
            max_attempts=1,
            overlap_policy="forbid",
        ),
    ]
