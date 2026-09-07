"""Tests for the portfolio_utils job definitions (issue #1934).

Fully offline. Asserts the two registered jobs, their schedules and default
params, that handlers return a core ``JobResult`` (with warnings on partial
failure/cancellation), parameter validation through each definition's
Pydantic model, that neither params nor results ever carry an API key, and
that the pyproject advertises the ``openbb_job_extension`` entry point.
"""

from __future__ import annotations

from pathlib import Path

import portfolio_utils.jobs as jobs_module
import pytest
from openbb_core.app.jobs.models import JobContext, JobDefinition, JobResult
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.jobs.schedules import DailySchedule
from portfolio_utils.fetch_position_history import PositionHistoryWarmResult
from portfolio_utils.jobs import (
    EtfHoldingsJobParams,
    PositionHistoryJobParams,
    get_job_definitions,
)
from portfolio_utils.refresh_etf_holdings_cache import EtfHoldingsWarmResult


def _by_name() -> dict[str, JobDefinition]:
    return {d.name: d for d in get_job_definitions()}


def _context(job_name: str) -> JobContext:
    return JobContext(run_id="r1", job_name=job_name)


def test_get_job_definitions_returns_both_jobs():
    """Both portfolio cache-warmer jobs are defined with the expected names."""
    names = {d.name for d in get_job_definitions()}
    assert names == {"portfolio.position_history", "portfolio.etf_holdings"}


def test_definitions_register_without_duplicates():
    """The definitions load cleanly into a JobRegistry (allowlist discovery)."""
    registry = JobRegistry.discover([get_job_definitions])
    assert "portfolio.position_history" in registry
    assert "portfolio.etf_holdings" in registry


def test_position_history_schedule_is_weekday_0100_local():
    """position_history runs weekdays at 01:00 in the resolved local zone."""
    definition = _by_name()["portfolio.position_history"]
    schedule = definition.schedule
    assert isinstance(schedule, DailySchedule)
    assert (schedule.hour, schedule.minute) == (1, 0)
    assert schedule.weekdays == (0, 1, 2, 3, 4)
    assert definition.overlap_policy == "forbid"


def test_etf_holdings_schedule_is_weekday_0200_local():
    """etf_holdings runs weekdays at 02:00 in the resolved local zone."""
    definition = _by_name()["portfolio.etf_holdings"]
    schedule = definition.schedule
    assert isinstance(schedule, DailySchedule)
    assert (schedule.hour, schedule.minute) == (2, 0)
    assert schedule.weekdays == (0, 1, 2, 3, 4)
    assert definition.overlap_policy == "forbid"


def test_timezone_env_override(monkeypatch):
    """OPENBB_JOBS_TIMEZONE overrides both schedules' timezone."""
    monkeypatch.setenv("OPENBB_JOBS_TIMEZONE", "Europe/London")
    definitions = _by_name()
    assert definitions["portfolio.position_history"].schedule.timezone == "Europe/London"
    assert definitions["portfolio.etf_holdings"].schedule.timezone == "Europe/London"


def test_default_params_validate_against_models():
    """Default params validate against each job's Pydantic model."""
    definitions = _by_name()
    PositionHistoryJobParams.model_validate(
        definitions["portfolio.position_history"].default_params
    )
    EtfHoldingsJobParams.model_validate(
        definitions["portfolio.etf_holdings"].default_params
    )


def test_job_params_never_carry_credentials_or_database_overrides():
    """Jobs use the worker's configured provider database and expose no secrets."""
    for model in (PositionHistoryJobParams, EtfHoldingsJobParams):
        field_names = set(model.model_fields)
        assert "database" not in field_names
        assert not any(
            "key" in name.lower() or "credential" in name.lower() or "secret" in name.lower()
            for name in field_names
        ), f"{model.__name__} unexpectedly exposes a credential-shaped field: {field_names}"


@pytest.mark.parametrize("model", [PositionHistoryJobParams, EtfHoldingsJobParams])
def test_job_params_reject_unsupported_overrides(model):
    """Unsupported database, credential, and dry-run overrides fail explicitly."""
    for field in ("database", "api_key", "dry_run"):
        with pytest.raises(ValueError, match="Extra inputs are not permitted"):
            model.model_validate({field: "unexpected"})


def test_position_history_handler_returns_job_result(monkeypatch):
    """The handler wraps run_position_history_warm and returns a JobResult."""
    captured = {}

    def _fake_run(**kwargs):
        captured.update(kwargs)
        return PositionHistoryWarmResult(
            requested_symbols=3,
            success=["AAPL", "MSFT"],
            failed=[{"symbol": "ZZZZ", "error": "boom"}],
            total_rows=100,
            start_date="2020-01-01",
            end_date="2025-01-01",
            years=5,
            dry_run=False,
            cancelled=False,
            readiness={},
        )

    monkeypatch.setattr(jobs_module, "run_position_history_warm", _fake_run)
    definition = _by_name()["portfolio.position_history"]
    params = PositionHistoryJobParams(years=5)
    result = definition.handler(_context(definition.name), params)

    assert isinstance(result, JobResult)
    assert result.summary["success_count"] == 2
    assert result.summary["failed_count"] == 1
    assert result.warnings == ["ZZZZ: boom"]
    assert result.has_warnings  # -> JobRun.complete() classifies succeeded_with_warnings
    # Params were threaded through, and should_cancel was wired for cooperative
    # cancellation between symbols (see _should_cancel's docstring).
    assert captured["years"] == 5
    assert callable(captured["should_cancel"])
    assert captured["should_cancel"]() is False


def test_position_history_handler_no_failures_has_no_warnings(monkeypatch):
    """A fully successful run reports no warnings (plain succeeded)."""

    def _fake_run(**kwargs):
        return PositionHistoryWarmResult(
            requested_symbols=2,
            success=["AAPL", "MSFT"],
            failed=[],
            total_rows=50,
            start_date="2020-01-01",
            end_date="2025-01-01",
            years=5,
            dry_run=False,
            cancelled=False,
            readiness={},
        )

    monkeypatch.setattr(jobs_module, "run_position_history_warm", _fake_run)
    definition = _by_name()["portfolio.position_history"]
    result = definition.handler(_context(definition.name), PositionHistoryJobParams())

    assert not result.has_warnings
    assert result.warnings == []


def test_position_history_handler_reports_cancellation_as_warning(monkeypatch):
    """A cancelled run still succeeds but is flagged with a warning."""

    def _fake_run(**kwargs):
        return PositionHistoryWarmResult(
            requested_symbols=5,
            success=["AAPL"],
            failed=[],
            total_rows=10,
            start_date="2020-01-01",
            end_date="2025-01-01",
            years=5,
            dry_run=False,
            cancelled=True,
            readiness={},
        )

    monkeypatch.setattr(jobs_module, "run_position_history_warm", _fake_run)
    definition = _by_name()["portfolio.position_history"]
    result = definition.handler(_context(definition.name), PositionHistoryJobParams())

    assert result.has_warnings
    assert any("cancelled" in w for w in result.warnings)


def test_position_history_handler_never_threads_a_credential_kwarg(monkeypatch):
    """The handler never passes an API key/credential kwarg to the warm function.

    ``run_position_history_warm`` resolves its own FMP credential internally
    (``api_key_resolver``, defaulted from ``_resolve_api_key``) -- the handler
    must not accept, resolve, or forward one via job params, matching the
    Global Constraint that the API/persistence layer never stores credentials.
    """
    captured = {}

    def _fake_run(**kwargs):
        captured.update(kwargs)
        return PositionHistoryWarmResult(requested_symbols=0, years=5)

    monkeypatch.setattr(jobs_module, "run_position_history_warm", _fake_run)
    definition = _by_name()["portfolio.position_history"]
    definition.handler(_context(definition.name), PositionHistoryJobParams())

    assert not any(
        "key" in name.lower() or "credential" in name.lower() or "secret" in name.lower()
        for name in captured
    )


def test_etf_holdings_handler_returns_job_result(monkeypatch):
    """The handler wraps run_etf_holdings_warm and returns a JobResult."""
    captured = {}

    def _fake_run(**kwargs):
        captured.update(kwargs)
        return EtfHoldingsWarmResult(
            spdr_count=11,
            portfolio_etfs=["QQQ"],
            extras=[],
            universe=["XLE", "QQQ"],
            requested=2,
            populated=1,
            errored=1,
            empty=0,
            cancelled=False,
            elapsed_seconds=1.234,
            dry_run=False,
        )

    monkeypatch.setattr(jobs_module, "run_etf_holdings_warm", _fake_run)
    definition = _by_name()["portfolio.etf_holdings"]
    result = definition.handler(_context(definition.name), EtfHoldingsJobParams())

    assert isinstance(result, JobResult)
    assert result.summary["populated"] == 1
    assert result.summary["errored"] == 1
    assert result.has_warnings
    assert "1 of 2 ETF(s) failed" in result.warnings[0]
    assert "api_key" not in captured  # never threaded through from params
    assert callable(captured["should_cancel"])


def test_etf_holdings_handler_no_errors_has_no_warnings(monkeypatch):
    """A fully successful ETF refresh reports no warnings."""

    def _fake_run(**kwargs):
        return EtfHoldingsWarmResult(
            spdr_count=11,
            portfolio_etfs=[],
            extras=[],
            universe=["XLE"],
            requested=1,
            populated=1,
            errored=0,
            empty=0,
            cancelled=False,
            elapsed_seconds=0.5,
            dry_run=False,
        )

    monkeypatch.setattr(jobs_module, "run_etf_holdings_warm", _fake_run)
    definition = _by_name()["portfolio.etf_holdings"]
    result = definition.handler(_context(definition.name), EtfHoldingsJobParams())

    assert not result.has_warnings
    assert result.warnings == []


def test_pyproject_advertises_job_entry_point():
    """The portfolio_utils pyproject registers the openbb_job_extension entry point."""
    pyproject = Path(__file__).resolve().parents[1] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "openbb_job_extension" in text
    assert "portfolio_utils.jobs:get_job_definitions" in text
