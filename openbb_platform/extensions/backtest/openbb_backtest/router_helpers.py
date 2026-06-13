"""Shared router substrate: engine selection, privacy boundary, plumbing (C09.1).

Helpers every ``obb.backtest.*`` sub-router builds on, kept free of heavy imports
so they load at ``import openbb`` time:

- :func:`resolve_engine` — normalize ``engine="auto"|"vector"|"event"`` (and the
  canonical ``"vectorized"``) to a concrete engine name. ``"auto"`` prefers the
  vectorized engine, switching to the event-driven engine for path-dependent /
  Pipeline strategies. Unknown names raise :class:`EngineSelectionError`.
- :func:`sanitize_result` — the **privacy boundary**: outward responses carry
  normalized returns/metrics only; raw ``positions`` (and any lot detail) are
  stripped before a result leaves the router (fork privacy rule). Returns a copy;
  the caller's object is never mutated.
- :func:`resolve_provider` / :func:`required_credentials` — credential plumbing
  that deals only in provider/credential *names*. Secrets are resolved by the
  standard OpenBB credential system downstream; this module never reads or
  returns plaintext secret values.

See ``docs/designs/backtest-design/09-api-surface.md`` §1–§2.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from openbb_backtest.errors import EngineSelectionError
from openbb_backtest.models import BacktestConfig, BacktestResult
from openbb_backtest.settings import DEFAULT_SETTINGS

if TYPE_CHECKING:
    from openbb_backtest.interfaces import DataFeed

logger = logging.getLogger(__name__)

#: Canonical concrete engine names (match the ``@register_engine`` registrations).
_VECTORIZED = "vectorized"
_EVENT = "event"

#: Accepted ``engine=`` inputs mapped to their canonical concrete engine name.
#: ``"auto"`` is resolved separately by policy (see :func:`resolve_engine`).
_ENGINE_ALIASES: dict[str, str] = {
    "vectorized": _VECTORIZED,
    "vector": _VECTORIZED,
    "vec": _VECTORIZED,
    "event": _EVENT,
    "event_driven": _EVENT,
    "event-driven": _EVENT,
}

#: Every engine selection input the router accepts (for error messages).
_AVAILABLE_ENGINES = ["auto", *sorted({*_ENGINE_ALIASES, _VECTORIZED, _EVENT})]

#: Credential names each provider needs; resolved by the platform, not here.
_PROVIDER_CREDENTIALS: dict[str, list[str]] = {
    "fmp_cached": ["fmp_cached_api_key"],
}


def resolve_engine(engine: str, *, path_dependent: bool = False) -> str:
    """Resolve an ``engine=`` selection to a concrete engine name.

    Parameters
    ----------
    engine
        ``"auto"``, ``"vector"``/``"vectorized"``, or ``"event"`` (case-insensitive).
    path_dependent
        Hint used only when ``engine="auto"``: path-dependent or Pipeline
        strategies route to the event-driven engine; everything else stays on the
        vectorized engine.

    Returns
    -------
    str
        ``"vectorized"`` or ``"event"``.

    Raises
    ------
    EngineSelectionError
        If ``engine`` is not a recognized selection.
    """
    key = engine.strip().lower()
    if key == "auto":
        chosen = _EVENT if path_dependent else _VECTORIZED
        logger.debug("engine=auto resolved to %s (path_dependent=%s)", chosen, path_dependent)
        return chosen
    try:
        return _ENGINE_ALIASES[key]
    except KeyError:
        raise EngineSelectionError(engine, available=_AVAILABLE_ENGINES) from None


def sanitize_result(result: BacktestResult) -> BacktestResult:
    """Strip raw position/lot detail before a result crosses the router.

    Returns a copy of ``result`` with ``positions`` emptied; metrics, the equity
    curve, trades, engine name and config are preserved. The input is not
    mutated (fork privacy rule — only normalized returns/metrics leave the API).
    """
    sanitized = result.model_copy(update={"positions": []})
    logger.debug(
        "sanitized result: dropped %d position snapshot(s)", len(result.positions)
    )
    return sanitized


def resolve_provider(provider: str | None) -> str:
    """Return the data provider name, defaulting to the fork's ``fmp_cached``.

    Only the provider *name* is resolved here; the platform's credential system
    supplies the actual secrets downstream.
    """
    return provider or DEFAULT_SETTINGS.default_provider


def build_feed(config: BacktestConfig, provider: str) -> DataFeed:
    """Build the point-in-time :class:`DataFeed` for ``config`` from ``provider``.

    Loads the columnar bundle the ``fmp_cached`` ingestor persists (component 03),
    so the same look-ahead-safe reader backs every engine and pipeline. Credentials
    are resolved by the standard OpenBB provider system, not here. The heavy
    ``data.bundle`` import stays inside the body to keep ``import openbb`` light.

    Each ``obb.backtest.*`` sub-router keeps a thin module-level ``_build_feed``
    seam that delegates here, so unit tests can monkeypatch the seam per router
    while the ingest/load logic lives in exactly one place.
    """
    from openbb_backtest.data.bundle import Bundle, BundleIngestor, FmpCachedReader

    reader = FmpCachedReader()
    ingestor = BundleIngestor(reader, calendar=config.calendar)
    meta = ingestor.ingest(
        list(config.universe), config.start, config.end, name=provider
    )
    return Bundle.load(DEFAULT_SETTINGS.bundle_root, name=meta.name)


def required_credentials(provider: str | None = None) -> list[str]:
    """Return the credential *names* a provider needs (never their values).

    The returned strings are keys the standard OpenBB credential system resolves
    from ``user_settings.json`` / environment; this helper never reads or returns
    plaintext secrets.
    """
    name = resolve_provider(provider)
    return list(_PROVIDER_CREDENTIALS.get(name, []))
