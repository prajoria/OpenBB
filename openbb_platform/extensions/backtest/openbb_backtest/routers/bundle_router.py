"""Bundle sub-router: ``bundle.ingest`` / ``bundle.list`` (component 09.5).

The data-management face of ``obb.backtest.*``, exposed under the nested
``obb.backtest.bundle.*`` namespace (realized by the router ``prefix="/bundle"``).
Two commands sit on top of the component-03 columnar data bundle:

- :func:`ingest` drives :class:`~openbb_backtest.data.bundle.BundleIngestor` — the
  cache-first ``fmp_cached`` MySQL -> calendar-aligned parquet path — and returns
  the written bundle's :class:`~openbb_backtest.models.BundleInfo`. The provider
  (and its credentials) are resolved through the standard plumbing
  (:func:`~openbb_backtest.router_helpers.resolve_provider`); no secret is read
  here, and the heavy ``data.bundle`` import stays lazy to keep ``import openbb``
  light.
- :func:`list` enumerates the on-disk bundle store (there is **no** registry):
  each child directory holding a ``metadata.json`` becomes one
  :class:`BundleInfo`. The atomic-save ``.{name}.tmp`` partials are skipped so a
  half-written bundle never surfaces.

See ``docs/designs/backtest-design/09-api-surface.md`` §1 and
``03-data-bundle.md``.
"""

from __future__ import annotations

import builtins
import json
import logging
from dataclasses import asdict
from typing import TYPE_CHECKING

from openbb_core.app.model.example import PythonEx
from openbb_core.app.model.obbject import OBBject
from openbb_core.app.router import Router

from openbb_backtest.models import BacktestConfig, BundleInfo
from openbb_backtest.router_helpers import resolve_provider
from openbb_backtest.settings import DEFAULT_SETTINGS

if TYPE_CHECKING:
    from openbb_backtest.data.bundle import BundleIngestor, BundleMetadata

logger = logging.getLogger(__name__)

router = Router(prefix="/bundle", description="Ingest and list backtest data bundles.")


# --- collaborator seams (patched in unit tests; lazy in production) ------


def _build_ingestor(config: BacktestConfig) -> BundleIngestor:
    """Construct the :class:`BundleIngestor` over the live ``fmp_cached`` reader.

    The reader (and its MySQL driver) is imported lazily so ``import openbb`` stays
    light and so unit tests can monkeypatch this seam with an in-memory fake instead
    of touching a database. The calendar comes from the config so the ingest aligns
    to the same sessions the backtest will run on.
    """
    from openbb_backtest.data.bundle import BundleIngestor, FmpCachedReader

    return BundleIngestor(FmpCachedReader(), calendar=config.calendar)


def _bundle_root() -> str:
    """Return the on-disk bundle store root (a seam so tests can use ``tmp_path``).

    Sourced from settings so the writer (``ingest``) and the reader
    (``router_helpers.build_feed``) read the same one place and can never
    silently drift apart.
    """
    return DEFAULT_SETTINGS.bundle_root


def _info_from_mapping(meta: dict, default_name: str) -> BundleInfo:
    """Build a :class:`BundleInfo` from a ``metadata.json`` mapping.

    The single mapping point for both the ingest path (:func:`_to_info`, via the
    dataclass's ``asdict``) and the on-disk listing (:func:`list`). Only the
    descriptive fields are copied — never any internal ``extra`` bag — so the
    on-disk store layout stays encapsulated behind the API. ``default_name`` backs
    the bundle's directory name when the payload omits ``name``.
    """
    return BundleInfo(
        name=meta.get("name") or default_name,
        symbols=[*meta.get("symbols", [])],
        calendar=meta.get("calendar", DEFAULT_SETTINGS.default_calendar),
        start=meta.get("start"),
        end=meta.get("end"),
        ingested_at=meta.get("ingested_at"),
        has_fundamentals=bool(meta.get("has_fundamentals", False)),
    )


def _to_info(meta: BundleMetadata) -> BundleInfo:
    """Map an internal :class:`BundleMetadata` to the public :class:`BundleInfo`.

    Shares the field-copying logic with the on-disk listing via
    :func:`_info_from_mapping`, so the ingest and ``list`` paths can never
    describe the same bundle two different ways.
    """
    return _info_from_mapping(asdict(meta), default_name=meta.name)


# --- commands ------------------------------------------------------------


@router.command(
    methods=["POST"],
    examples=[
        PythonEx(
            description="Ingest a universe into a named fmp_cached data bundle.",
            code=[
                "from openbb_backtest.models import BacktestConfig",
                'config = BacktestConfig(strategy="buy_and_hold", universe=["AAPL", "MSFT"], start="2020-01-01", end="2023-01-01")',  # noqa: E501
                'obb.backtest.bundle.ingest(config=config, name="my_bundle")',
            ],
        ),
    ],
)
def ingest(
    config: BacktestConfig,
    name: str | None = None,
    provider: str | None = None,
) -> OBBject[BundleInfo]:
    """Ingest the config's universe and date range into a persisted data bundle.

    Reads the cache-first ``fmp_cached`` source, aligns bars to the config calendar,
    back-adjusts for corporate actions, and writes a columnar parquet bundle to the
    store root. When ``name`` is omitted the bundle is named after the resolved
    provider, so the engine routers' feed loader can read it back by provider name.

    Parameters
    ----------
    config : BacktestConfig
        Universe, date range and calendar define what is ingested.
    name : str, optional
        Bundle name (store sub-directory); defaults to the resolved provider name.
    provider : str, optional
        Data provider name; defaults to the fork's ``fmp_cached``.

    Returns
    -------
    OBBject[BundleInfo]
        Descriptor of the written bundle (name, symbols, calendar, dates).
    """
    provider_name = resolve_provider(provider)
    bundle_name = name or provider_name
    logger.debug(
        "bundle.ingest: name=%s universe=%s provider=%s",
        bundle_name, config.universe, provider_name,
    )

    ingestor = _build_ingestor(config)
    meta = ingestor.ingest(
        [*config.universe],
        config.start,
        config.end,
        name=bundle_name,
        root=_bundle_root(),
    )
    return OBBject(results=_to_info(meta))


@router.command(
    methods=["GET"],
    examples=[
        PythonEx(
            description="List every data bundle ingested into the local store.",
            code=["obb.backtest.bundle.list()"],
        ),
    ],
)
def list() -> OBBject[builtins.list[BundleInfo]]:  # noqa: A001 - public name is the API contract
    """List the data bundles persisted in the local store.

    Enumerates the store root (there is no separate registry): each child directory
    carrying a ``metadata.json`` is reported as one :class:`BundleInfo`, ordered by
    name. A missing store root (nothing ever ingested) and the ``.{name}.tmp``
    partials left by the atomic save both yield no entry rather than an error.

    Returns
    -------
    OBBject[list[BundleInfo]]
        One descriptor per persisted bundle (empty when none exist).
    """
    from pathlib import Path

    root = Path(_bundle_root())
    bundles: builtins.list[BundleInfo] = []
    if not root.is_dir():
        return OBBject(results=bundles)

    for child in sorted(root.iterdir()):
        # Skip the atomic-save partials (".{name}.tmp"); only fully-renamed
        # bundle directories carry a metadata.json at their final location.
        if not child.is_dir() or child.name.startswith("."):
            continue
        try:
            meta = json.loads((child / "metadata.json").read_text())
            if not isinstance(meta, dict):
                raise ValueError("metadata.json is not an object")
            bundles.append(_info_from_mapping(meta, default_name=child.name))
        except (OSError, ValueError) as exc:
            # A missing, unreadable, truncated/corrupt, or wrong-shape
            # metadata.json must not take down the whole listing -- degrade
            # gracefully, consistent with skipping half-written bundles.
            logger.warning("bundle.list: skipping %s (%s)", child.name, exc)
            continue
    logger.debug("bundle.list: found %d bundle(s) under %s", len(bundles), root)
    return OBBject(results=bundles)
