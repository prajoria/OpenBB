"""Pydantic request/response models for the P1 sub-routers (D3 §4).

Centralized here (rather than co-located with each router) so the four files
share one source of truth — the ``test_attribution_surfaces`` test introspects
:class:`PineHealth.powered_by` here, and the typed-vs-bare OBBject rule from
D3 §5 means several models are referenced from more than one router (e.g.
``PineRunRequest`` is built once and re-shaped for ``/pine/strategies/run``).

Models match D3 §4 contracts field-for-field; deviations are flagged in the
parent bead report.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

__all__ = [
    # Response models
    "PineCompileResponse",
    "BundledIndicatorEntry",
    "BundledStrategyEntry",
    "BuiltinsCoverage",
    "PineHealth",
    # Request models
    "PineByoData",
    "PineRunRequest",
    "PineCompileRequest",
    "PineStrategiesRunRequest",
]


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class PineCompileResponse(BaseModel):
    """``POST /pine/compile`` typed response (D3 §4.2).

    A small stable schema -> ``OBBject[PineCompileResponse]`` per D3 §5
    ("typed model when the keys are ours"). ``python_source`` carries a
    stub message at M1 since codegen (C5, bead 0e9.5.5) has not landed —
    ``builtins_used`` is populated from the type checker (C3) once it
    becomes importable, else stays empty.
    """

    python_source: str = Field(
        description="Emitted @pyne module text (or a stub message until C5 lands)."
    )
    sha: str = Field(
        description=(
            "blake2b digest cache key (source ‖ params ‖ compiler_version "
            "‖ pine_version) — matches /pine/run's cache key once C5+C6 land."
        )
    )
    pine_version: int = Field(
        description="Detected //@version= integer (5 or 6).",
        ge=5,
        le=6,
    )
    compiler_version: str = Field(
        description="``openbb_pine.__version__`` at the time of compile."
    )
    builtins_used: list[str] = Field(
        default_factory=list,
        description=(
            "Sorted fully-qualified Pine builtin identifiers the script "
            "references — populated by C3 once it lands; [] in the M1 stub."
        ),
    )
    warnings: list[str] = Field(
        default_factory=list,
        description=(
            "v5->v6 migration notes, deprecated builtins, etc. — "
            "M1 surface returns [] (C7 migration shim lands later)."
        ),
    )


class BundledIndicatorEntry(BaseModel):
    """One entry in ``GET /pine/indicators/list`` (D3 §4.4).

    M1 returns ``[]`` — bundled indicators land with the Workspace widgets
    P2 bead. This model locks the shape so widget configs can be generated
    from it via ``mcp/registration.build_tool_spec`` (D3 §7.2).
    """

    name: str = Field(
        description='Stable slug, e.g. "bollinger_bands". Used in MCP tool name.'
    )
    pine_source_path: str = Field(
        description="Path within the extension to the bundled .pine source."
    )
    description: str = Field(
        description="One-line human-readable description (also used as MCP description)."
    )
    category: str = Field(
        description=(
            'One of: "indicator" | "strategy" | "library". '
            "Strategies are reserved for M2 (PRD §3.2)."
        )
    )
    pine_version: int = Field(
        description="Pine version of the bundled source (5 or 6).",
        ge=5,
        le=6,
    )


class BundledStrategyEntry(BaseModel):
    """One entry in ``GET /pine/strategies/list`` (D3 §4.4 sibling, #588).

    Same "catalog projection" shape as :class:`BundledIndicatorEntry` but
    carries the two strategy-only fields the run/backtest layer needs to
    render defaults in a widget's params form:

    * ``strategy_type`` — one of ``"long_only"``, ``"short_only"``,
      ``"long_short"``. Mirrors Pine's ``strategy(..., default_qty_type,
      ...)`` positional-vs-keyword surface. Widgets use it to gate the
      long-vs-short toggle.
    * ``initial_capital_default`` — the ``strategy(..., initial_capital=...)``
      default the widget pre-fills. Pine's own default is 100_000 (see
      TradingView docs / `strategy.equity` sourcing); we match it verbatim.

    ``pine_source_path`` uses the same ``"inline:<id>"`` convention as the
    indicators catalog — the Pine source lives verbatim in the bundled
    ``strategies.json`` entry's ``params.source`` rather than a separate
    ``.pine`` file. This is deliberate: it keeps the shipped asset
    single-file (one JSON) so packaging via ``importlib.resources`` in
    Phase 4 stays trivial.
    """

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description='Human-readable strategy name, e.g. "RSI Reversal".')
    pine_source_path: str = Field(
        description=(
            'Location of the bundled Pine source. Uses the ``"inline:<id>"`` '
            "convention when the source is embedded in strategies.json rather "
            "than shipped as a separate .pine file."
        )
    )
    description: str = Field(
        description="One-line human-readable description of the strategy."
    )
    strategy_type: Literal["long_only", "short_only", "long_short"] = Field(
        default="long_short",
        description=(
            "Direction constraint the strategy honors. Defaults to "
            '``"long_short"`` (widest surface) when the catalog entry omits it.'
        ),
    )
    initial_capital_default: float = Field(
        default=100_000.0,
        gt=0.0,
        description=(
            "Default initial capital pre-filled by the widget. Matches Pine's "
            "own ``strategy(..., initial_capital=100_000)`` default."
        ),
    )
    pine_version: int = Field(
        default=6,
        description="Pine version of the bundled source (5 or 6).",
        ge=5,
        le=6,
    )


class BuiltinsCoverage(BaseModel):
    """``GET /pine/builtins/coverage`` typed response (D3 §4.5).

    Read from :mod:`openbb_pine._coverage_manifest` — the single source of
    truth for "what's implemented." Phase 0 reports zero counts; each PR
    that lands a builtin updates the manifest, which automatically updates
    this endpoint's payload.
    """

    pine_versions_supported: list[int] = Field(
        description="Pine ``//@version=`` integers the compiler accepts unedited."
    )
    builtins_implemented_count: int = Field(
        description="Number of fully-qualified Pine builtins implemented.",
        ge=0,
    )
    builtins_implemented: list[str] = Field(
        description="Sorted fully-qualified Pine builtin identifiers implemented."
    )
    features_implemented: list[str] = Field(
        description=(
            "Sorted grammar features implemented (closed vocabulary from "
            "the wild-corpus indexer)."
        )
    )
    pine_versions_known: list[int] = Field(
        description=(
            "What we COULD support if more shims land — the universe of "
            "Pine versions the compiler architecture targets."
        )
    )


class PineHealth(BaseModel):
    """``GET /pine/health`` typed response (D3 §4.6).

    Operator-focused health-check payload — locked as a typed model so the
    §2.6 attribution surface #3 lives in the OpenAPI schema. ``status`` is
    derived from the shared :func:`openbb_pine.diagnostics.run_all_checks`
    output (same backend as ``obb.pine.about()``).

    Per D3 §8.2 (and the 4-of-4 attribution test), ``powered_by`` MUST equal
    the literal :data:`openbb_pine.attribution.POWERED_BY_SHORT` — the SHORT
    form is correct here because the field key already says "powered_by".
    """

    # Every field has a sensible default so `PineHealth()` constructs
    # without args — this lets the 4-of-4 attribution test (surface #3
    # branch) introspect the `powered_by` default without having to know
    # which fields are required. The defaults are "unknown / not-yet
    # populated" placeholders; the real router populates every field
    # before returning.
    #
    # `extra="forbid"` rejects typo'd kwargs at runtime — callers must
    # spell field names correctly.
    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded", "unhealthy"] = Field(
        default="unhealthy",
        description=(
            '"ok" when doctor_ok=True; "degraded" when any check is WARN; '
            '"unhealthy" when any check is FAIL or unknown.'
        ),
    )
    extension_version: str = Field(
        default="0.0.0",
        description="Installed ``openbb-extension-pine`` package version.",
    )
    pine_version_supported: str = Field(
        default="6",
        description='e.g. "6" or "6 (and v5 via auto-migration)".',
    )
    compiler_status: str = Field(
        default="unknown",
        description=(
            "Free-form compiler status string — locked to a typed enum "
            "once codegen (C5) ships."
        ),
    )
    runtime: str = Field(
        default="PyneCore (unknown version)",
        description='e.g. "PyneCore 6.5.2 (Apache-2.0)".',
    )
    powered_by: str = Field(
        default_factory=lambda: _powered_by_short_default(),
        description=(
            "PyneSys §4(d) attribution — §2.6 surface #3. MUST equal "
            "``openbb_pine.attribution.POWERED_BY_SHORT``."
        ),
    )
    doctor_ok: bool = Field(
        default=False,
        description="True iff every diagnostic check returned OK or WARN (no FAIL).",
    )
    doctor_issues: list[str] = Field(
        default_factory=list,
        description="Names of failing checks (empty when doctor_ok=True).",
    )
    fmp_key_present: bool = Field(
        default=False,
        description="Mirrors the doctor's FMP-key check status.",
    )
    fmp_cached_installed: bool = Field(
        default=False,
        description="True iff ``openbb_fmp_cached`` is importable.",
    )


def _powered_by_short_default() -> str:
    """Late-binding default for ``PineHealth.powered_by``.

    Importing :data:`openbb_pine.attribution.POWERED_BY_SHORT` directly at
    module import time would shape-couple the model file to the attribution
    file; sourcing via a default factory keeps the 4-of-4 attribution test's
    "single source of truth" guarantee — a future move of the literal only
    touches ``attribution.py``.
    """
    from openbb_pine.attribution import POWERED_BY_SHORT

    return POWERED_BY_SHORT


# ---------------------------------------------------------------------------
# Request models — POST endpoints
# ---------------------------------------------------------------------------


class PineByoData(BaseModel):
    """BYO-OHLCV payload (PRD §4.10, D3 §4.1).

    Validated shape only — actual fetching of ``parquet_url`` / ``csv_url``
    / ``arrow_ipc_base64`` payloads is deferred to a Phase 1 follow-up bead
    (see "OUT OF SCOPE" in the parent design). ``records`` is the only
    format that the M1 runtime accepts end-to-end today.
    """

    format: Literal["records", "parquet_url", "csv_url", "arrow_ipc_base64"] = Field(
        description="Payload encoding — only 'records' is wired end-to-end at M1."
    )
    tz: str = Field(
        default="UTC",
        description="IANA timezone for the bar timestamps (default UTC).",
    )
    records: list[dict[str, Any]] | None = Field(
        default=None,
        description="Inline OHLCV records when format='records'.",
    )
    url: str | None = Field(
        default=None,
        description="Source URL when format ∈ {parquet_url, csv_url}.",
    )
    data_b64: str | None = Field(
        default=None,
        description="Base64-encoded payload when format='arrow_ipc_base64'.",
    )

    @model_validator(mode="after")
    def _format_payload_matches(self) -> PineByoData:
        """Each format MUST carry the field its name implies."""
        if self.format == "records" and not self.records:
            raise ValueError("format='records' requires non-empty `records`")
        if self.format in ("parquet_url", "csv_url") and not self.url:
            raise ValueError(f"format={self.format!r} requires `url`")
        if self.format == "arrow_ipc_base64" and not self.data_b64:
            raise ValueError("format='arrow_ipc_base64' requires `data_b64`")
        return self


class PineRunRequest(BaseModel):
    """``POST /pine/run`` request body (D3 §4.1, PRD §4.8 + §4.8.2).

    Two mutually-mostly-exclusive modes:

    * **Provider mode**: ``provider`` + ``symbol`` populated; FMP-only per
      PRD §13.8 (non-FMP value -> :class:`PineProviderError`).
    * **BYO mode**: ``data`` populated; ``symbol`` recommended but not
      required (``syminfo.*`` returns ``na`` when omitted).

    If both are supplied, ``data`` wins for the primary series and the
    response carries a warning (PRD §4.8.2). The validator only enforces
    that at least one is present.
    """

    source: str = Field(
        min_length=1,
        description="Pine v5 or v6 source text.",
    )
    provider: Literal["fmp", "fmp_cached"] | None = Field(
        default=None,
        description=(
            'Data provider. "fmp" or "fmp_cached" — PRD §13.8 locks this '
            "set in v1.x; non-FMP values raise PineProviderError."
        ),
    )
    symbol: str | None = Field(
        default=None,
        description="Ticker — required in provider mode, recommended in BYO mode.",
    )
    interval: str | None = Field(
        default=None,
        description='Bar interval, e.g. "1d", "1h" — defaults to "1d" in the runtime.',
    )
    start: datetime | None = Field(
        default=None,
        description="ISO date / datetime for the start of the primary series.",
    )
    end: datetime | None = Field(
        default=None,
        description="ISO date / datetime for the end of the primary series.",
    )
    params: dict[str, Any] = Field(
        default_factory=dict,
        description="Pine input overrides — keyed by input variable name.",
    )
    data: PineByoData | None = Field(
        default=None,
        description="BYO OHLCV payload — mutually mostly-exclusive with provider+symbol.",
    )
    timeout_s: int | None = Field(
        default=None,
        ge=1,
        description="Per-script wall-clock cap; defaults to the runtime's DEFAULT_TIMEOUT_S.",
    )

    @model_validator(mode="after")
    def _exactly_one_data_source(self) -> PineRunRequest:
        """Either provider+symbol or data must be present (D3 §4.1)."""
        if self.data is None:
            if self.provider is None:
                raise ValueError("either `provider` (+ `symbol`) or `data` must be set")
            if self.symbol is None:
                raise ValueError(
                    "`symbol` is required when `provider` is set "
                    "(provider mode hits FMP and needs a ticker)"
                )
        return self


class PineCompileRequest(BaseModel):
    """``POST /pine/compile`` request body (D3 §4.2)."""

    source: str = Field(
        min_length=1,
        description="Pine v5 or v6 source text.",
    )
    target_version: int = Field(
        default=6,
        ge=5,
        le=6,
        description=(
            "Input version (5 or 6). Output is always v6 IR — the C7 migration "
            "shim will rewrite v5 sources to v6 when it lands; until then a "
            "v5 source raises PineUnsupportedFeatureError on any v5-only "
            "construct."
        ),
    )


class PineStrategiesRunRequest(PineRunRequest):
    """``POST /pine/strategies/run`` request body (D3 §4.3).

    Identical to :class:`PineRunRequest` plus ``strategy_params``. Defined
    so the OpenAPI schema for ``/pine/strategies/run`` is correct at M1
    even though the endpoint always returns HTTP 501 until M2.
    """

    strategy_params: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Strategy-specific keyword overrides (initial_capital, "
            "commission_type, slippage, etc.) — lands at M2 per PRD §3.2."
        ),
    )
