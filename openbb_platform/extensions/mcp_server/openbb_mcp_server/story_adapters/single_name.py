"""Seven-phase single-name analysis tool (#2314, N05b).

``POST /api/v1/story/analytics/single_name`` runs the repository's
``Analysis/stock_analysis.run_full_analysis`` (the pipeline behind the
portfolio/02 notebook) for one symbol and returns every phase result, the
gate diagnostics and the provenance of the run. It never reduces the
analysis to a single composite score.

The pipeline is not copied. ``Analysis/`` is not a packaged distribution, so
it is loaded from ``OPENBB_ANALYSIS_DIR`` or, by default, from the
repository checkout this server runs from; without it the tool answers 503.
Results are made strict JSON: frames return their columns, true row count
and latest ``max_frame_rows`` rows (10 by default, at most 50; a full MSFT
run with 50 is about 150 KiB), and NaN or infinity become ``null``. At most
``MAX_CONCURRENT_RUNS`` runs happen at once; further calls are refused.
"""

from __future__ import annotations

import copy
import dataclasses
import datetime
import enum
import hashlib
import importlib.util
import logging
import math
import os
import sys
import threading
from pathlib import Path
from types import ModuleType
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import BaseModel, ConfigDict, Field, model_validator

logger = logging.getLogger(__name__)

ANALYSIS_DIR_ENV = "OPENBB_ANALYSIS_DIR"
MODULE_NAME = "stock_analysis"
DEFAULT_FRAME_ROWS = 10
MAX_FRAME_ROWS = 50
MAX_CONCURRENT_RUNS = 2
RUN_SLOTS = threading.BoundedSemaphore(MAX_CONCURRENT_RUNS)
PHASES = tuple(f"p{i}" for i in range(1, 8))
FEATURE_FLAGS = (
    "use_two_stage_dcf",
    "use_sector_wacc",
    "use_confluence_engine",
    "use_regime_input",
    "use_trailing_stop",
    "use_stop_cap",
    "use_peg_tightening",
    "use_extended_confluence_panel",
)
_SYMBOL = Annotated[
    str, Field(min_length=1, max_length=10, pattern=r"^[A-Za-z0-9.\-]+$")
]
_load_lock = threading.Lock()


def default_analysis_dir() -> Path:
    """Return ``OPENBB_ANALYSIS_DIR`` or the checkout's ``Analysis/``."""
    configured = os.getenv(ANALYSIS_DIR_ENV)
    if configured:
        return Path(configured)
    # story_adapters -> openbb_mcp_server -> mcp_server -> extensions
    # -> openbb_platform -> repository root
    return Path(__file__).resolve().parents[5] / "Analysis"


def load_pipeline() -> ModuleType:
    """Return the ``stock_analysis`` module, loading it once if needed.

    Raises :class:`FileNotFoundError` when the pipeline is not present.
    """
    with _load_lock:
        loaded = sys.modules.get(MODULE_NAME)
        if loaded is not None and hasattr(loaded, "run_full_analysis"):
            return loaded
        path = default_analysis_dir() / f"{MODULE_NAME}.py"
        if not path.is_file():
            raise FileNotFoundError(path)
        spec = importlib.util.spec_from_file_location(MODULE_NAME, path)
        if spec is None or spec.loader is None:
            raise FileNotFoundError(path)
        module = importlib.util.module_from_spec(spec)
        # Registered under the name the pipeline's own tests and notebooks
        # use, so there is one module identity and one logger.
        sys.modules[MODULE_NAME] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(MODULE_NAME, None)
            raise
        return module


def _engine_sha256(module: ModuleType) -> str | None:
    source = getattr(module, "__file__", None)
    if not source:
        return None
    return hashlib.sha256(Path(source).read_bytes()).hexdigest()


def _json_value(  # noqa: PLR0911  # pylint: disable=too-many-return-statements
    value: Any, rows: int = MAX_FRAME_ROWS
) -> Any:
    """Convert a phase field into strict JSON."""
    # pylint: disable=import-outside-toplevel
    import numpy as np
    import pandas as pd

    if value is None or isinstance(value, bool | str):
        return value
    if isinstance(value, enum.Enum):
        return _json_value(value.value, rows)
    if isinstance(value, int | np.integer) and not isinstance(value, bool):
        return int(value)
    if isinstance(value, float | np.floating):
        number = float(value)
        return number if math.isfinite(number) else None
    if isinstance(value, np.bool_):
        return bool(value)
    if isinstance(value, pd.Timestamp | datetime.datetime | datetime.date):
        return None if pd.isna(value) else value.isoformat()
    if isinstance(value, pd.DataFrame):
        tail = value.tail(rows) if rows else value.iloc[0:0]
        return {
            "columns": [str(c) for c in value.columns],
            "row_count": int(len(value)),
            "rows": [
                {str(k): _json_value(v, rows) for k, v in row.items()}
                for row in tail.to_dict(orient="records")
            ],
        }
    if isinstance(value, pd.Series):
        return _json_value(value.tail(rows).to_dict() if rows else {}, rows)
    if isinstance(value, dict):
        return {str(k): _json_value(v, rows) for k, v in value.items()}
    if isinstance(value, list | tuple | set):
        return [_json_value(v, rows) for v in value]
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return _phase_fields(value, rows)
    if value is pd.NaT:
        return None
    return str(value)


def _phase_fields(result: Any, rows: int) -> dict[str, Any]:
    return {
        f.name: _json_value(getattr(result, f.name), rows)
        for f in dataclasses.fields(result)
    }


class SingleNameRequest(BaseModel):
    """One symbol and the pipeline's documented switches."""

    model_config = ConfigDict(extra="forbid")

    symbol: _SYMBOL
    benchmark: _SYMBOL = "SPY"
    feature_flags: dict[str, bool] = Field(
        default_factory=dict,
        description=f"Any of: {', '.join(FEATURE_FLAGS)}. Unset flags are off.",
    )
    max_frame_rows: int = Field(
        DEFAULT_FRAME_ROWS,
        ge=0,
        le=MAX_FRAME_ROWS,
        description="Latest rows returned per table; 0 returns columns and counts.",
    )
    enforce_gates: bool = Field(
        False, description="Stop at the first failed phase gate."
    )
    regime: (
        Literal["TRENDING_BULL", "RANGING", "TRENDING_BEAR", "CRISIS", "UNKNOWN"] | None
    ) = Field(
        None,
        description="Market regime for phase 7; requires use_regime_input.",
    )

    @model_validator(mode="before")
    @classmethod
    def _upper_regime(cls, data: Any) -> Any:
        if isinstance(data, dict) and isinstance(data.get("regime"), str):
            data = {**data, "regime": data["regime"].upper()}
        return data

    @model_validator(mode="after")
    def _known_switches(self) -> SingleNameRequest:
        unknown = sorted(set(self.feature_flags) - set(FEATURE_FLAGS))
        if unknown:
            raise ValueError(f"unknown feature flags: {', '.join(unknown)}")
        flags = dict(self.feature_flags)
        if self.regime is not None and not flags.get("use_regime_input"):
            raise ValueError(
                "regime has no effect unless feature_flags.use_regime_input is true"
            )
        return self


class PhaseGate(BaseModel):
    """One phase's gate outcome."""

    phase: str
    gate_passed: bool | None
    gate_notes: str | None


class Diagnostics(BaseModel):
    """How far the pipeline ran and how each gate went."""

    gates: list[PhaseGate]
    stopped_at: str | None
    phases_not_run: list[str]


class SingleNameResponse(BaseModel):
    """Every phase result, diagnostics and provenance."""

    phases: dict[str, dict[str, Any]]
    diagnostics: Diagnostics
    provenance: dict[str, Any]


def _run(request: SingleNameRequest) -> SingleNameResponse:
    try:
        module = load_pipeline()
    except FileNotFoundError as exc:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "The Analysis pipeline (Analysis/stock_analysis.py) is not available "
            f"to this server; set {ANALYSIS_DIR_ENV} to its directory.",
        ) from exc
    flags = module.AnalysisFeatureFlags(**request.feature_flags)
    cfg = module.AnalysisConfig(
        symbol=request.symbol.upper(),
        benchmark=request.benchmark.upper(),
        enforce_gates=request.enforce_gates,
        feature_flags=flags,
    )
    regime = None
    if request.regime is not None:
        from openbb_regime import (  # pylint: disable=import-outside-toplevel
            MarketRegime,
        )

        regime = MarketRegime(request.regime)
    try:
        results = module.run_full_analysis(cfg, regime=regime)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning("story single-name analysis failed for %s: %s", cfg.symbol, exc)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"The analysis of {cfg.symbol} failed ({type(exc).__name__}); "
            "no partial result was returned.",
        ) from exc

    rows = request.max_frame_rows
    phases = {
        key: _phase_fields(results[key], rows) for key in PHASES if key in results
    }
    stopped_at = results.get("stopped_at")
    if stopped_at in PHASES:
        # The engine synthesizes a "Gate Failed" phase 7 when it stops early;
        # it is not a decision, so it is reported as not run.
        ran = PHASES[: PHASES.index(stopped_at) + 1]
        phases = {key: value for key, value in phases.items() if key in ran}
    gates = [
        PhaseGate(
            phase=key,
            gate_passed=phases[key].get("gate_passed"),
            gate_notes=phases[key].get("gate_notes"),
        )
        for key in PHASES
        if key in phases
    ]
    return SingleNameResponse(
        phases=phases,
        diagnostics=Diagnostics(
            gates=gates,
            stopped_at=stopped_at,
            phases_not_run=[key for key in PHASES if key not in phases],
        ),
        provenance={
            "engine": "Analysis/stock_analysis.run_full_analysis",
            "engine_sha256": _engine_sha256(module),
            "symbol": cfg.symbol,
            "benchmark": cfg.benchmark,
            "provider": cfg.provider,
            "start_fundamentals": cfg.start_fundamentals,
            "start_technicals": cfg.start_technicals,
            "end_date": cfg.end_date,
            "enforce_gates": cfg.enforce_gates,
            "feature_flags": dataclasses.asdict(flags),
            "regime": request.regime,
            "max_frame_rows": rows,
        },
    )


def build_router() -> APIRouter:
    """Return the single-name analysis route."""
    router = APIRouter(prefix="/api/v1/story/analytics", tags=["story"])

    @router.post(
        "/single_name",
        operation_id="story_single_name_analysis",
        dependencies=[Depends(AuthService().auth_hook)],
        openapi_extra={"mcp_config": {"name": "story_single_name_analysis"}},
    )
    def story_single_name_analysis(request: SingleNameRequest) -> SingleNameResponse:
        """Run the seven-phase single-name analysis for one symbol.

        Returns company, fundamentals, technicals, valuation, risk,
        peer-relative and decision results with every field, each phase's
        gate, where the pipeline stopped (with ``enforce_gates``) and the
        provenance of the run. Data comes from ``fmp_cached``.
        """
        # A non-blocking acquire, released in the ``finally`` below.
        if not RUN_SLOTS.acquire(blocking=False):  # pylint: disable=consider-using-with
            raise HTTPException(
                status.HTTP_429_TOO_MANY_REQUESTS,
                f"{MAX_CONCURRENT_RUNS} analyses are already running; retry later.",
            )
        try:
            return _run(request)
        finally:
            RUN_SLOTS.release()

    return router


def compose_single_name_app(source_app: FastAPI) -> FastAPI:
    """Add the single-name analysis route to an isolated app copy."""
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router())
    composed.openapi_schema = None
    return composed
