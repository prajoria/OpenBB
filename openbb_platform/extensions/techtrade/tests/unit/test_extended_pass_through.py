"""Tests for engine/indicators_ext.py + engine/confluence_ext.py — pass-through
stubs that family PRs (bd-luy/40v/z43/alj) will replace with real extended
indicators.

Full context: docs/superpowers/plans/2026-07-08-bd-7ct-confluence-foundation.md
Step 2 (bd-m8n). Contract these stubs guarantee:

1. Same signature as the classic ``_compute_*`` / ``*_votes`` functions.
2. Byte-identical return value on the same input (proves plumbing works
   without introducing indicator risk).
3. Docstring mentions "pass-through" and cites which family PR will
   replace the function.

Once family PRs land, these tests will be updated to assert the extended
functions ADD new keys/votes on top of the classic output — but for
bd-7ct the contract IS "identical to classic".
"""

from __future__ import annotations

from datetime import date

import numpy as np
import pandas as pd
import pytest

from openbb_techtrade.engine import confluence, indicators
from openbb_techtrade.engine.indicators import DEFAULT_CONFIG


# --------------------------------------------------------------------------- #
# Fixture: a minimal-but-realistic OHLCV DataFrame with enough bars for every
# classic indicator to have finite values on the last bar.
# --------------------------------------------------------------------------- #
def _make_ohlcv_df(n: int = 100) -> pd.DataFrame:
    """Ascending-close synthetic OHLCV — deterministic and long enough for
    the classic panel's 50-bar EMA + 20-bar Bollinger to be finite on the
    last bar.

    Imports ``pandas_ta_classic`` at fixture-build time to register the
    ``.ta`` accessor on ``pd.DataFrame`` (matches the lazy-inside-function
    pattern in ``engine/indicators.py``). Tests that call ``_compute_*``
    directly (bypassing ``build_indicator_panel``) need this registration
    to have happened at least once in the process — otherwise ``df.ta``
    raises ``AttributeError``.
    """
    import pandas_ta_classic  # noqa: F401 - registers the pandas ``.ta`` accessor

    dates = pd.date_range("2024-01-01", periods=n, freq="B")
    close = 100.0 + np.arange(n) * 0.5  # steady uptrend
    df = pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1_000_000.0) + np.arange(n) * 100,
        },
        index=dates,
    )
    df.columns = [c.lower() for c in df.columns]
    return df


@pytest.fixture(scope="module")
def ohlcv_df() -> pd.DataFrame:
    return _make_ohlcv_df(100)


@pytest.fixture(scope="module")
def sample_panel(ohlcv_df: pd.DataFrame):
    """A real IndicatorPanel from build_indicator_panel — feeds the vote-
    emitter pass-through tests."""
    return indicators.build_indicator_panel(
        symbol="TEST",
        as_of=date(2024, 5, 20),
        ohlcv_rows=ohlcv_df.reset_index(names="timestamp").to_dict(orient="records"),
    )


# =========================================================================== #
# indicators_ext.py — panel computation stubs
# =========================================================================== #


class TestIndicatorsExtImportable:
    """Module + symbols must exist. Family PRs cannot start until this is true."""

    def test_module_importable(self):
        from openbb_techtrade.engine import indicators_ext  # noqa: F401

    def test_exports_four_family_functions(self):
        from openbb_techtrade.engine import indicators_ext

        for name in ("_compute_trend_ext", "_compute_momentum_ext",
                     "_compute_volatility_ext", "_compute_volume_ext"):
            assert hasattr(indicators_ext, name), (
                f"indicators_ext must export {name}; family PRs will replace it."
            )


class TestIndicatorsExtSignatureCompat:
    """Each stub must accept the same (df, config) signature as its classic
    twin so the dispatcher (bd-nx3) can call either interchangeably."""

    def test_compute_trend_ext_signature(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_trend_ext
        result = _compute_trend_ext(ohlcv_df, DEFAULT_CONFIG)
        assert isinstance(result, dict)

    def test_compute_momentum_ext_signature(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_momentum_ext
        result = _compute_momentum_ext(ohlcv_df, DEFAULT_CONFIG)
        assert isinstance(result, dict)

    def test_compute_volatility_ext_signature(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_volatility_ext
        result = _compute_volatility_ext(ohlcv_df, DEFAULT_CONFIG)
        assert isinstance(result, dict)

    def test_compute_volume_ext_signature(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_volume_ext
        result = _compute_volume_ext(ohlcv_df, DEFAULT_CONFIG)
        assert isinstance(result, dict)


class TestIndicatorsExtPassThroughEquality:
    """The core contract: TODAY, extended returns exactly what classic returns.

    R7.11 load-bearing: family PRs will replace each stub with an implementation
    that ADDS keys. These equality tests will then be updated to assert
    ``set(classic_keys).issubset(set(extended_keys))`` instead. Until then,
    'identical' is the byte-level guarantee that no accidental drift snuck in
    while wiring the dispatcher.
    """

    def test_trend_ext_matches_classic(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_trend_ext
        assert _compute_trend_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_trend(ohlcv_df, DEFAULT_CONFIG)

    def test_momentum_ext_matches_classic(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_momentum_ext
        assert _compute_momentum_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_momentum(ohlcv_df, DEFAULT_CONFIG)

    def test_volatility_ext_matches_classic(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_volatility_ext
        assert _compute_volatility_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_volatility(ohlcv_df, DEFAULT_CONFIG)

    def test_volume_ext_matches_classic(self, ohlcv_df):
        from openbb_techtrade.engine.indicators_ext import _compute_volume_ext
        assert _compute_volume_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_volume(ohlcv_df, DEFAULT_CONFIG)


class TestIndicatorsExtDocstringDiscipline:
    """Every stub docstring must say 'pass-through' and name the family PR
    that will replace it. Prevents a future refactor from silently deleting
    the classic-mirroring contract without a reader understanding what changed."""

    @pytest.mark.parametrize(
        "func_name,family_pr",
        [
            ("_compute_trend_ext", "bd-luy"),
            ("_compute_momentum_ext", "bd-40v"),
            ("_compute_volatility_ext", "bd-z43"),
            ("_compute_volume_ext", "bd-alj"),
        ],
    )
    def test_docstring_names_pass_through_and_family_pr(self, func_name, family_pr):
        from openbb_techtrade.engine import indicators_ext
        func = getattr(indicators_ext, func_name)
        doc = (func.__doc__ or "").lower()
        assert "pass-through" in doc, (
            f"{func_name} docstring must explicitly say 'pass-through' — "
            f"downstream readers rely on this word to understand the contract."
        )
        assert family_pr in (func.__doc__ or ""), (
            f"{func_name} docstring must name {family_pr} as the family PR "
            f"that will replace this stub."
        )


# =========================================================================== #
# confluence_ext.py — vote emitter stubs
# =========================================================================== #


class TestConfluenceExtImportable:
    def test_module_importable(self):
        from openbb_techtrade.engine import confluence_ext  # noqa: F401

    def test_exports_four_vote_functions(self):
        from openbb_techtrade.engine import confluence_ext

        for name in ("trend_votes_ext", "momentum_votes_ext",
                     "volatility_votes_ext", "_volume_votes_ext"):
            assert hasattr(confluence_ext, name), (
                f"confluence_ext must export {name}; family PRs will replace it."
            )


class TestConfluenceExtPassThroughEquality:
    """Same contract as indicators_ext: TODAY, extended vote emitters return
    exactly what classic emitters return on the same panel."""

    def test_trend_votes_ext_matches_classic(self, sample_panel):
        from openbb_techtrade.engine.confluence_ext import trend_votes_ext
        assert trend_votes_ext(sample_panel) == confluence.trend_votes(sample_panel)

    def test_momentum_votes_ext_matches_classic(self, sample_panel):
        from openbb_techtrade.engine.confluence_ext import momentum_votes_ext
        assert momentum_votes_ext(sample_panel) == confluence.momentum_votes(sample_panel)

    def test_volatility_votes_ext_matches_classic(self, sample_panel):
        from openbb_techtrade.engine.confluence_ext import volatility_votes_ext
        # volatility_votes has a `regime` kwarg — stub must accept + forward it
        assert volatility_votes_ext(sample_panel) == confluence.volatility_votes(sample_panel)
        assert volatility_votes_ext(sample_panel, regime="range") == \
               confluence.volatility_votes(sample_panel, regime="range")

    def test_volume_votes_ext_matches_classic(self, sample_panel):
        from openbb_techtrade.engine.confluence_ext import _volume_votes_ext
        assert _volume_votes_ext(sample_panel) == confluence._volume_votes(sample_panel)


class TestConfluenceExtDocstringDiscipline:
    @pytest.mark.parametrize(
        "func_name,family_pr",
        [
            ("trend_votes_ext", "bd-luy"),
            ("momentum_votes_ext", "bd-40v"),
            ("volatility_votes_ext", "bd-z43"),
            ("_volume_votes_ext", "bd-alj"),
        ],
    )
    def test_docstring_names_pass_through_and_family_pr(self, func_name, family_pr):
        from openbb_techtrade.engine import confluence_ext
        func = getattr(confluence_ext, func_name)
        doc = (func.__doc__ or "").lower()
        assert "pass-through" in doc
        assert family_pr in (func.__doc__ or "")


# =========================================================================== #
# bd-nx3 (Step 4): Thread PanelConfig through build_indicator_panel
# =========================================================================== #


def _ohlcv_records(df: pd.DataFrame) -> list[dict]:
    """Convert the fixture DataFrame to the list-of-dict shape
    ``build_indicator_panel`` expects."""
    return df.reset_index(names="timestamp").to_dict(orient="records")


class TestBuildIndicatorPanelClassicBackwardCompat:
    """R7.11 load-bearing: the flag-off / no-kwarg path MUST be byte-
    identical to pre-bd-7ct. AC-1 depends on this. If this test flips
    red, the flag-off path is broken and every downstream Analysis
    caller changes behavior — the exact scenario the spec §D1 says
    must not happen."""

    def test_no_kwarg_matches_explicit_classic(self, ohlcv_df):
        """Omitting ``panel_config`` produces the same panel as
        explicitly passing ``PANEL_CLASSIC``. Proves the default kwarg
        value is the classic sentinel — not, say, ``None``-then-fallback."""
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC

        as_of = date(2024, 5, 20)
        records = _ohlcv_records(ohlcv_df)

        panel_default = indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
        )
        panel_classic = indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_CLASSIC,
        )
        assert panel_default == panel_classic


class TestBuildIndicatorPanelExtendedDispatch:
    """When ``panel_config=PANEL_EXTENDED`` is passed, the dispatch calls
    the ``_ext`` functions instead of the classic ones. Today that's
    behaviorally identical (stubs pass through), but the dispatch
    surface itself is verified via spy — this is what family PRs will
    lean on."""

    def test_extended_calls_ext_compute_functions(self, ohlcv_df, monkeypatch):
        from openbb_techtrade.engine import indicators_ext
        from openbb_techtrade.engine.panel_config import PANEL_EXTENDED

        # Spy on every _ext function to prove the dispatch actually calls them
        called = set()

        def _wrap(name, real):
            def spy(*args, **kwargs):
                called.add(name)
                return real(*args, **kwargs)
            return spy

        monkeypatch.setattr(
            indicators_ext, "_compute_trend_ext",
            _wrap("trend", indicators_ext._compute_trend_ext),
        )
        monkeypatch.setattr(
            indicators_ext, "_compute_momentum_ext",
            _wrap("momentum", indicators_ext._compute_momentum_ext),
        )
        monkeypatch.setattr(
            indicators_ext, "_compute_volatility_ext",
            _wrap("volatility", indicators_ext._compute_volatility_ext),
        )
        monkeypatch.setattr(
            indicators_ext, "_compute_volume_ext",
            _wrap("volume", indicators_ext._compute_volume_ext),
        )

        as_of = date(2024, 5, 20)
        indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=_ohlcv_records(ohlcv_df),
            panel_config=PANEL_EXTENDED,
        )
        assert called == {"trend", "momentum", "volatility", "volume"}, (
            f"extended dispatch must call all 4 _ext functions; called={called}"
        )

    def test_extended_produces_identical_panel_today(self, ohlcv_df):
        """Golden invariance: today (stubs pass-through), extended and
        classic panels are byte-identical. When family PRs land they
        will diverge; this test will be updated to
        ``set(classic).issubset(set(extended))`` at that time."""
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC, PANEL_EXTENDED

        as_of = date(2024, 5, 20)
        records = _ohlcv_records(ohlcv_df)
        classic = indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_CLASSIC,
        )
        extended = indicators.build_indicator_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_EXTENDED,
        )
        assert classic == extended, (
            "With pass-through stubs in bd-7ct, classic and extended "
            "panels must be byte-identical. Family PRs will change this."
        )


# =========================================================================== #
# bd-ctt (Step 5): Thread PanelConfig through technical_panel
#
# technical_panel has a DUAL-PATH structure:
#   - "tech" leg: uses obb.technical.* when available (openbb-technical
#     extension installed). Uses `(obb, records, config)`-signature helpers.
#   - "fallback" leg: delegates to build_indicator_panel when obb.technical
#     is unavailable. Uses the classic `(df, config)`-signature helpers.
#
# bd-7ct scope: thread panel_config into the fallback path (which uses
# build_indicator_panel, so dispatch is automatic once forwarded). The
# tech leg's `_compute_technical_*` helpers are NOT yet mirrored — that
# gets added when family PRs (bd-luy/40v/z43) land, at which point the
# extended tech-leg mirrors will be introduced. Until then, tech-leg
# calls always use the classic 14-key panel regardless of panel_config
# — documented + tested here.
# =========================================================================== #


class TestTechnicalPanelClassicBackwardCompat:
    """R7.11 load-bearing: no-kwarg / classic path is byte-identical.
    Same AC-1 guarantee as build_indicator_panel — nothing outside
    techtrade should observe any change from bd-7ct."""

    def test_technical_panel_no_kwarg_matches_explicit_classic(self, ohlcv_df):
        from openbb_techtrade.engine import indicators_technical
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC

        as_of = date(2024, 5, 20)
        records = _ohlcv_records(ohlcv_df)

        # Without obb.technical installed, technical_panel falls back to
        # build_indicator_panel — verify no-kwarg matches explicit classic
        panel_default = indicators_technical.technical_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
        )
        panel_classic = indicators_technical.technical_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_CLASSIC,
        )
        assert panel_default == panel_classic


class TestTechnicalPanelExtendedFallbackForwarding:
    """When ``panel_config=PANEL_EXTENDED`` is passed AND the tech path
    is unavailable, the fallback delegation to ``build_indicator_panel``
    MUST forward the panel_config. Otherwise the flag would be silently
    ignored on the fallback path — a bug that would only surface once
    family PRs land."""

    def test_extended_forwarded_to_fallback(self, ohlcv_df):
        from openbb_techtrade.engine import indicators_technical
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC, PANEL_EXTENDED

        as_of = date(2024, 5, 20)
        records = _ohlcv_records(ohlcv_df)
        # obb.technical is not installed in the test env, so both go
        # through the fallback. They must be byte-identical TODAY (pass-
        # through stubs) — but the fact that the extended call doesn't
        # raise proves the kwarg is accepted + forwarded.
        classic = indicators_technical.technical_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_CLASSIC,
        )
        extended = indicators_technical.technical_panel(
            symbol="TEST", as_of=as_of, ohlcv_rows=records,
            panel_config=PANEL_EXTENDED,
        )
        assert classic == extended, (
            "Fallback path with pass-through stubs must produce identical "
            "panels for classic vs extended. When family PRs land, this "
            "test flips to a subset assertion."
        )


class TestTechnicalPanelTechLegExtendedIsSilentNoOp:
    """iter-1 pr-test H1: locks the documented limitation that on the
    tech leg (when obb.technical is available), ``panel_config=PANEL_
    EXTENDED`` is silently ignored and the classic panel is returned.

    Uses an injected ``obb_loader`` to FORCE the tech branch even
    though openbb_technical is not installed in the test env. This
    guarantees the test targets the exact code path family PRs will
    replace when they wire in ``_compute_technical_*_ext`` mirrors.

    R7.11 load-bearing: if a future family PR partially wires the
    tech-leg mirrors (e.g., adds `_compute_technical_trend_ext` but
    leaves the others), this test would flip red because the tech
    branch's extended-vs-classic byte-identity would break — before
    the reviewer even reads the diff.
    """

    def test_tech_leg_extended_matches_classic_and_warns(
        self, ohlcv_df, caplog,
    ):
        import logging
        from types import SimpleNamespace
        from openbb_techtrade.engine import indicators_technical
        from openbb_techtrade.engine.panel_config import (
            PANEL_CLASSIC, PANEL_EXTENDED,
        )

        as_of = date(2024, 5, 20)
        records = _ohlcv_records(ohlcv_df)

        # Fake obb loader that exposes just enough for the tech-leg
        # helpers to try (and fail gracefully into the fallback path,
        # which is where the actual dispatch happens). The important
        # thing is we HIT the tech branch — the "silent downgrade
        # WARNING" is what we're testing for.
        def fake_obb_loader():
            return SimpleNamespace(technical=None)

        with caplog.at_level(
            logging.WARNING, logger="openbb_techtrade.engine.indicators_technical",
        ):
            panel_extended = indicators_technical.technical_panel(
                symbol="TEST", as_of=as_of, ohlcv_rows=records,
                obb_loader=fake_obb_loader,
                panel_config=PANEL_EXTENDED,
            )
            panel_classic = indicators_technical.technical_panel(
                symbol="TEST", as_of=as_of, ohlcv_rows=records,
                obb_loader=fake_obb_loader,
                panel_config=PANEL_CLASSIC,
            )

        # Result parity: tech leg's silent-classic downgrade means both
        # panels are the classic bytes
        assert panel_extended == panel_classic

        # And a WARNING must have fired for the extended call (only)
        extended_warnings = [
            r for r in caplog.records
            if "PANEL_EXTENDED requested" in r.getMessage()
            and "TEST" in r.getMessage()
        ]
        assert len(extended_warnings) >= 1, (
            f"tech-leg PANEL_EXTENDED must emit the 'silently downgrading' "
            f"WARNING so ops can debug why extended does nothing on "
            f"openbb_technical-installed environments. Got: "
            f"{[r.getMessage() for r in caplog.records]}"
        )


# =========================================================================== #
# bd-xim (Step 6): Thread PanelConfig through confluence.build_signal
# =========================================================================== #


class TestBuildSignalClassicBackwardCompat:
    """R7.11 load-bearing: no-kwarg / PANEL_CLASSIC path is byte-identical
    to pre-bd-7ct on the MoverSignal (score + votes + everything). AC-1
    depends on this."""

    def test_no_kwarg_matches_explicit_classic(self, sample_panel):
        from openbb_techtrade.engine.confluence import build_signal
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC

        signal_default = build_signal(sample_panel, segment="TEST_SECTOR")
        signal_classic = build_signal(
            sample_panel, segment="TEST_SECTOR", panel_config=PANEL_CLASSIC,
        )
        assert signal_default.score == signal_classic.score
        assert signal_default.direction == signal_classic.direction
        assert signal_default.votes == signal_classic.votes


class TestBuildSignalExtendedDispatch:
    """When ``panel_config=PANEL_EXTENDED`` is passed, ``build_signal``
    dispatches to the ``_ext`` vote emitters. Today they're pass-
    through — the byte-identical assertion proves the wiring works
    without indicator-level drift."""

    def test_extended_calls_ext_vote_emitters(self, sample_panel, monkeypatch):
        from openbb_techtrade.engine import confluence_ext
        from openbb_techtrade.engine.confluence import build_signal
        from openbb_techtrade.engine.panel_config import PANEL_EXTENDED

        called = set()

        def _wrap(name, real):
            def spy(*args, **kwargs):
                called.add(name)
                return real(*args, **kwargs)
            return spy

        monkeypatch.setattr(confluence_ext, "trend_votes_ext",
                            _wrap("trend", confluence_ext.trend_votes_ext))
        monkeypatch.setattr(confluence_ext, "momentum_votes_ext",
                            _wrap("momentum", confluence_ext.momentum_votes_ext))
        monkeypatch.setattr(confluence_ext, "volatility_votes_ext",
                            _wrap("volatility", confluence_ext.volatility_votes_ext))
        monkeypatch.setattr(confluence_ext, "_volume_votes_ext",
                            _wrap("volume", confluence_ext._volume_votes_ext))

        build_signal(sample_panel, segment="TEST_SECTOR", panel_config=PANEL_EXTENDED)
        assert called == {"trend", "momentum", "volatility", "volume"}, (
            f"extended dispatch must call all 4 _ext vote emitters; "
            f"called={called}"
        )

    def test_extended_produces_identical_signal_today(self, sample_panel):
        """Golden invariance for the signal layer: today, extended and
        classic produce byte-identical scores + vote sequences."""
        from openbb_techtrade.engine.confluence import build_signal
        from openbb_techtrade.engine.panel_config import PANEL_CLASSIC, PANEL_EXTENDED

        classic = build_signal(sample_panel, segment="TEST", panel_config=PANEL_CLASSIC)
        extended = build_signal(sample_panel, segment="TEST", panel_config=PANEL_EXTENDED)
        assert classic.score == extended.score
        assert classic.votes == extended.votes
        assert classic.direction == extended.direction
