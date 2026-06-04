"""Runtime settings for the backtest extension.

Database access reuses the fmp_cached ``DatabaseConfig`` (component 03); no new
secrets are introduced here. API credentials continue to resolve from
``~/.openbb_platform/user_settings.json`` / environment.
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class BacktestSettings(BaseSettings):
    """Environment-configurable backtest defaults (prefix ``OPENBB_BACKTEST_``)."""

    model_config = SettingsConfigDict(env_prefix="OPENBB_BACKTEST_", extra="ignore")

    default_calendar: str = "XNYS"
    default_engine: str = "auto"
    reconcile_tolerance: float = 1e-6
    seed: int = 0
    export_dir: str = "Analysis/exports"


DEFAULT_SETTINGS = BacktestSettings()
