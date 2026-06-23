"""Unit tests for the nested bundle sub-router: ingest / list (component 09.5).

Like the engine (09.2), factor (09.3) and validate (09.4) routers, this router is
orchestration, not math. Two commands sit on top of the component-03 data bundle
under the nested ``obb.backtest.bundle.*`` namespace:

- :func:`ingest` drives :class:`~openbb_backtest.data.bundle.BundleIngestor` (the
  cache-first fmp_cached -> parquet path, faked here behind ``_build_ingestor``)
  and returns the written :class:`~openbb_backtest.models.BundleInfo`.
- :func:`list` enumerates the bundle store root (there is **no** registry) and
  reads each ``metadata.json`` into a :class:`BundleInfo`, skipping the
  ``.{name}.tmp`` partial directories the atomic save leaves behind.

The live MySQL reader is exercised only behind the ``integration`` marker; these
unit tests inject a fake ingestor and a ``tmp_path`` store root so they stay
hermetic (no DB, no network).

See ``docs/designs/backtest-design/09-api-surface.md`` §1 and
``03-data-bundle.md``.
"""

from __future__ import annotations

import json
from dataclasses import asdict
from datetime import date
from decimal import Decimal

# ---- shared fakes / builders --------------------------------------------


def _config(**kw):
    from openbb_backtest.models import BacktestConfig

    params = dict(
        strategy="c095_fake",
        universe=["AAA", "BBB"],
        start=date(2021, 1, 4),
        end=date(2021, 1, 8),
        engine="auto",
        initial_cash=Decimal("100000"),
    )
    params.update(kw)
    return BacktestConfig(**params)


def _meta(name: str = "fmp_cached", symbols=("AAA", "BBB"), has_fundamentals=False):
    """Build a :class:`BundleMetadata` mirroring what ``Bundle.save`` persists."""
    from openbb_backtest.data.bundle import BundleMetadata

    return BundleMetadata(
        name=name,
        symbols=list(symbols),
        calendar="XNYS",
        start="2021-01-04",
        end="2021-01-08",
        ingested_at="2021-01-09T00:00:00+00:00",
        has_fundamentals=has_fundamentals,
    )


class _FakeIngestor:
    """Records the ``ingest`` call and returns a deterministic metadata object."""

    def __init__(self, meta=None):
        self._meta = meta if meta is not None else _meta()
        self.calls: list[dict] = []

    def ingest(self, symbols, start, end, name="default", root=".openbb_backtest/bundles"):
        self.calls.append(
            dict(symbols=list(symbols), start=start, end=end, name=name, root=root)
        )
        return self._meta


def _write_metadata(root, meta) -> None:
    """Write a bundle directory with a ``metadata.json`` (as ``Bundle.save`` does)."""
    bundle_dir = root / meta.name
    bundle_dir.mkdir(parents=True)
    (bundle_dir / "metadata.json").write_text(json.dumps(asdict(meta), indent=2))


# ---- BundleInfo data model ----------------------------------------------


def test_bundle_info_data_model_roundtrips():
    from openbb_backtest.models import BundleInfo

    info = BundleInfo(
        name="fmp_cached",
        symbols=["AAA", "BBB"],
        calendar="XNYS",
        start="2021-01-04",
        end="2021-01-08",
        ingested_at="2021-01-09T00:00:00+00:00",
        has_fundamentals=True,
    )
    dumped = info.model_dump()
    assert dumped["name"] == "fmp_cached"
    assert dumped["symbols"] == ["AAA", "BBB"]
    assert dumped["calendar"] == "XNYS"
    assert dumped["has_fundamentals"] is True


def test_bundle_info_optional_fields_default_to_none():
    # A minimally-described bundle (only name + symbols + calendar) is valid;
    # the date/timestamp fields are optional so a not-yet-dated bundle round-trips.
    from openbb_backtest.models import BundleInfo

    info = BundleInfo(name="x", symbols=[], calendar="XNYS")
    assert info.start is None
    assert info.end is None
    assert info.ingested_at is None
    assert info.has_fundamentals is False


# ---- ingest --------------------------------------------------------------


def test_bundle_ingest_returns_obbject_bundle_info(monkeypatch):
    from openbb_backtest.models import BundleInfo
    from openbb_backtest.routers import bundle_router as br
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(br, "_build_ingestor", lambda config: _FakeIngestor())
    out = br.ingest(_config())
    assert isinstance(out, OBBject)
    assert isinstance(out.results, BundleInfo)
    assert out.results.name == "fmp_cached"
    assert out.results.symbols == ["AAA", "BBB"]
    assert out.results.calendar == "XNYS"


def test_bundle_ingest_forwards_universe_dates_and_root(monkeypatch, tmp_path):
    from openbb_backtest.routers import bundle_router as br

    fake = _FakeIngestor()
    monkeypatch.setattr(br, "_build_ingestor", lambda config: fake)
    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    cfg = _config(universe=["MSFT", "AAPL"], start=date(2020, 1, 1), end=date(2020, 6, 30))
    br.ingest(cfg, name="my_bundle")
    assert fake.calls == [
        dict(
            symbols=["MSFT", "AAPL"],
            start=date(2020, 1, 1),
            end=date(2020, 6, 30),
            name="my_bundle",
            root=str(tmp_path),
        )
    ]


def test_bundle_ingest_defaults_name_to_resolved_provider(monkeypatch):
    # With no explicit bundle name, the bundle is named after the resolved
    # provider (the fork's fmp_cached) so the engine's build_feed can load it back
    # by provider name -- consistent with router_helpers.build_feed(name=provider).
    from openbb_backtest.routers import bundle_router as br

    fake = _FakeIngestor()
    monkeypatch.setattr(br, "_build_ingestor", lambda config: fake)
    br.ingest(_config(), provider=None)
    assert fake.calls[0]["name"] == "fmp_cached"


# ---- list ----------------------------------------------------------------


def test_bundle_list_empty_when_no_bundles(monkeypatch, tmp_path):
    from openbb_backtest.routers import bundle_router as br
    from openbb_core.app.model.obbject import OBBject

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    out = br.list()
    assert isinstance(out, OBBject)
    assert out.results == []


def test_bundle_list_empty_when_root_missing(monkeypatch, tmp_path):
    # A store root that was never created (no bundle ever ingested) lists empty
    # rather than raising -- list must not assume the directory exists.
    from openbb_backtest.routers import bundle_router as br

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path / "never_created"))
    assert br.list().results == []


def test_bundle_list_returns_ingested_bundles(monkeypatch, tmp_path):
    from openbb_backtest.models import BundleInfo
    from openbb_backtest.routers import bundle_router as br

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    _write_metadata(tmp_path, _meta(name="alpha", symbols=["AAA"]))
    _write_metadata(tmp_path, _meta(name="beta", symbols=["BBB", "CCC"], has_fundamentals=True))

    out = br.list()
    assert all(isinstance(b, BundleInfo) for b in out.results)
    # Deterministic order (sorted by directory name).
    assert [b.name for b in out.results] == ["alpha", "beta"]
    beta = out.results[1]
    assert beta.symbols == ["BBB", "CCC"]
    assert beta.has_fundamentals is True
    assert beta.calendar == "XNYS"


def test_bundle_list_skips_partial_temp_dirs(monkeypatch, tmp_path):
    # Bundle.save writes to a sibling ``.{name}.tmp`` dir (which also holds a
    # metadata.json) before the atomic rename; a crash can leave one behind. list
    # must not surface these half-written bundles.
    from openbb_backtest.routers import bundle_router as br

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    _write_metadata(tmp_path, _meta(name="good"))
    _write_metadata(tmp_path, _meta(name=".good.tmp"))  # partial temp dir

    names = [b.name for b in br.list().results]
    assert names == ["good"]


def test_bundle_list_skips_corrupt_metadata(monkeypatch, tmp_path):
    # A truncated/corrupt metadata.json (e.g. a crash mid-write, or a non-dict
    # payload) must not take down the whole listing: list degrades gracefully,
    # skipping the bad bundle and still returning the good ones -- consistent with
    # its "never surface a half-written bundle" posture.
    from openbb_backtest.routers import bundle_router as br

    monkeypatch.setattr(br, "_bundle_root", lambda: str(tmp_path))
    _write_metadata(tmp_path, _meta(name="good"))
    # Corrupt: invalid JSON.
    bad = tmp_path / "corrupt"
    bad.mkdir()
    (bad / "metadata.json").write_text("{not valid json")
    # Wrong shape: valid JSON but not an object.
    wrong = tmp_path / "wrong_shape"
    wrong.mkdir()
    (wrong / "metadata.json").write_text("[1, 2, 3]")

    names = [b.name for b in br.list().results]
    assert names == ["good"]


def test_bundle_root_defaults_to_settings():
    # The store root is sourced from one place (settings) so the writer (ingest)
    # and reader (engine build_feed) can never silently drift apart.
    from openbb_backtest.routers import bundle_router as br
    from openbb_backtest.settings import DEFAULT_SETTINGS

    assert br._bundle_root() == DEFAULT_SETTINGS.bundle_root


# ---- registration & nested namespace -------------------------------------


def test_bundle_routes_registered_under_bundle_prefix():
    from openbb_backtest.routers import bundle_router as br

    paths = {
        route.path
        for route in br.router.api_router.routes
        if hasattr(route, "path")
    }
    assert {"/bundle/ingest", "/bundle/list"} <= paths


def test_bundle_router_uses_bundle_prefix():
    # The nested namespace obb.backtest.bundle.* is realized by the router prefix.
    from openbb_backtest.routers import bundle_router as br

    assert br.router.prefix == "/bundle"


def test_bundle_router_attaches_to_parent_router():
    # Regression: the ``list`` command shadows the builtin ``list`` in the module
    # namespace, which breaks FastAPI's lazy eval of the stringized return
    # annotation (``list[BundleInfo]``) when the *parent* router re-includes the
    # sub-router. Importing the top-level router must therefore succeed and the
    # nested bundle routes must resolve under it.
    import importlib

    from openbb_backtest import backtest_router

    importlib.reload(backtest_router)
    paths = {
        route.path
        for route in backtest_router.router.api_router.routes
        if hasattr(route, "path")
    }
    assert {"/bundle/ingest", "/bundle/list"} <= paths
