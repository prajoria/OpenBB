"""doctor() — HealthReport builder used by both the router command and the CLI.

Best-effort probes: every check returns a bool (never raises); failures are
captured in warnings/errors lists on the returned HealthReport. This means
`obb.fmp_trading.doctor()` always succeeds — the report itself tells you
what's wrong, which is far more useful than a cryptic exception.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import exchange_calendars as xcals

from openbb_fmp_trading.core.bandwidth import BandwidthMeter
from openbb_fmp_trading.models import HealthReport


def _extra_installed(pkg: str) -> bool:
    """True iff `pkg` resolves in the current environment via importlib.metadata."""
    try:
        version(pkg)
        return True
    except PackageNotFoundError:
        return False


def _check_fmp_credentials() -> bool:
    """True iff either fmp_cached_api_key or fmp_api_key is set in user settings."""
    try:
        from openbb_core.app.service.user_service import UserService

        creds = UserService().default_user_settings.credentials
        return bool(
            getattr(creds, "fmp_cached_api_key", None)
            or getattr(creds, "fmp_api_key", None)
        )
    except Exception:
        # Best-effort — a missing UserService is answerable as "no credentials",
        # not an exception to bubble up.
        return False


def _check_mysql_cache() -> bool:
    """True iff the fmp_cached MySQL cache is reachable.

    Uses a best-effort import + ping. Missing openbb_fmp_cached, missing
    pymysql, unreachable server all degrade to False rather than raising.
    """
    try:
        from openbb_fmp_cached.utils.helpers import ping_cache  # type: ignore

        return ping_cache()
    except Exception:
        return False


def _check_exchange_calendars() -> bool:
    """True iff exchange_calendars is importable and NASDAQ session works."""
    try:
        xcals.get_calendar("NASDAQ").is_session(date.today())
        return True
    except Exception:
        return False


def run_doctor(
    *,
    bandwidth_state_path: Path | str,
    bandwidth_budget_bytes: int,
    today: date | None = None,
) -> HealthReport:
    """Build and return a HealthReport for the current environment.

    Every probe is best-effort; the returned report has warnings/errors
    lists rather than raising. Callers decide policy: the router just
    returns the report; the CLI exits non-zero if errors is non-empty.
    """
    today = today or date.today()
    warnings: list[str] = []
    errors: list[str] = []

    try:
        tt_version = version("openbb-techtrade")
        tt_ok = True
    except PackageNotFoundError:
        tt_version = "0.0.0"
        tt_ok = False
        errors.append("openbb-techtrade not installed")

    fmp_ok = _check_fmp_credentials()
    if not fmp_ok:
        errors.append(
            "FMP credentials missing (set fmp_cached_api_key in user_settings.json)"
        )

    mysql_ok = _check_mysql_cache()
    if not mysql_ok:
        warnings.append(
            "fmp_cached MySQL cache unreachable — will fall back to raw fmp "
            "per tier-1 pattern"
        )

    xcals_ok = _check_exchange_calendars()
    if not xcals_ok:
        errors.append("exchange_calendars not available for NASDAQ")

    bw = BandwidthMeter(
        state_path=bandwidth_state_path,
        budget_bytes=bandwidth_budget_bytes,
        today=today,
    )
    remaining_pct = max(0.0, 100.0 * (1.0 - bw.state.month_used_pct))
    if bw.state.mode == "conservation":
        warnings.append(
            f"BandwidthMeter in conservation mode ({bw.state.month_used_pct:.1%} used)"
        )
    if bw.state.mode == "halted":
        errors.append(
            f"BandwidthMeter halted ({bw.state.month_used_pct:.1%} used) — "
            "new fetches will refuse until month rollover"
        )

    return HealthReport(
        ts=datetime.now(timezone.utc),
        fmp_credentials_ok=fmp_ok,
        mysql_cache_ok=mysql_ok,
        exchange_calendars_ok=xcals_ok,
        techtrade_version=tt_version,
        techtrade_ok=tt_ok,
        agent_extra_installed=_extra_installed("anthropic"),
        xlsxwriter_extra_installed=_extra_installed("xlsxwriter"),
        validation_extra_installed=_extra_installed("openbb-backtest"),
        bandwidth_remaining_pct=remaining_pct,
        warnings=warnings,
        errors=errors,
    )
