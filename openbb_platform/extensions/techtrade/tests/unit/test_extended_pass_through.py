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
    """The core contract: for still-pass-through families, TODAY extended
    returns exactly what classic returns. For the trend family (bd-luy
    shipped Aroon + Ichimoku), the contract relaxes to SUPERSET semantics:
    every classic key is present in extended, and extended may add new keys.

    R7.11 load-bearing: mutating _compute_trend_ext to drop a classic key
    must flip test_trend_ext_is_superset_of_classic red.
    """

    def test_trend_ext_is_superset_of_classic(self, ohlcv_df):
        """bd-luy shipped: extended trend adds Aroon + Ichimoku keys on
        top of classic. Contract is now SUBSET (classic keys ⊆ extended
        keys), not byte equality."""
        from openbb_techtrade.engine.indicators_ext import _compute_trend_ext
        extended = _compute_trend_ext(ohlcv_df, DEFAULT_CONFIG)
        classic = indicators._compute_trend(ohlcv_df, DEFAULT_CONFIG)
        assert set(classic.keys()).issubset(set(extended.keys())), (
            f"classic key(s) missing from extended: "
            f"{set(classic) - set(extended)}"
        )
        # Every shared key must still carry the same value (extended
        # only ADDS; it does not perturb classic values).
        for key, classic_value in classic.items():
            assert extended[key] == classic_value, (
                f"extended['{key}']={extended[key]!r} differs from "
                f"classic['{key}']={classic_value!r}"
            )

    def test_trend_ext_adds_new_keys(self, ohlcv_df):
        """The fixture uses 100 bars — enough for Aroon (25) but NOT
        Ichimoku (needs 78+26=78). So we expect Aroon keys but not
        Ichimoku ones on this fixture. If the fixture ever grows past
        78 bars, expect Ichimoku keys too."""
        from openbb_techtrade.engine.indicators_ext import _compute_trend_ext
        extended = _compute_trend_ext(ohlcv_df, DEFAULT_CONFIG)
        classic = indicators._compute_trend(ohlcv_df, DEFAULT_CONFIG)
        new_keys = set(extended) - set(classic)
        # Aroon keys always present on 100-bar fixture.
        assert {"aroon_up", "aroon_down", "aroon_osc"}.issubset(new_keys), (
            f"extended must add at least the 3 Aroon keys; new_keys={new_keys}"
        )

    def test_momentum_ext_matches_classic(self, ohlcv_df):
        """bd-40v not shipped yet — momentum still a pass-through."""
        from openbb_techtrade.engine.indicators_ext import _compute_momentum_ext
        assert _compute_momentum_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_momentum(ohlcv_df, DEFAULT_CONFIG)

    def test_volatility_ext_matches_classic(self, ohlcv_df):
        """bd-z43 not shipped yet — volatility still a pass-through."""
        from openbb_techtrade.engine.indicators_ext import _compute_volatility_ext
        assert _compute_volatility_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_volatility(ohlcv_df, DEFAULT_CONFIG)

    def test_volume_ext_matches_classic(self, ohlcv_df):
        """bd-alj not shipped yet — volume still a pass-through."""
        from openbb_techtrade.engine.indicators_ext import _compute_volume_ext
        assert _compute_volume_ext(ohlcv_df, DEFAULT_CONFIG) == \
               indicators._compute_volume(ohlcv_df, DEFAULT_CONFIG)


class TestIndicatorsExtDocstringDiscipline:
    """Every stub docstring must name the family PR that will replace it.
    For still-pass-through families it must also contain 'pass-through';
    for the trend family (bd-luy shipped), we drop that requirement since
    the function is no longer a pass-through."""

    @pytest.mark.parametrize(
        "func_name,family_pr,expect_pass_through",
        [
            ("_compute_trend_ext", "bd-luy", False),   # shipped
            ("_compute_momentum_ext", "bd-40v", True),  # still stub
            ("_compute_volatility_ext", "bd-z43", True),  # still stub
            ("_compute_volume_ext", "bd-alj", True),   # still stub
        ],
    )
    def test_docstring_names_pass_through_and_family_pr(
        self, func_name, family_pr, expect_pass_through
    ):
        from openbb_techtrade.engine import indicators_ext
        func = getattr(indicators_ext, func_name)
        doc = (func.__doc__ or "").lower()
        if expect_pass_through:
            assert "pass-through" in doc, (
                f"{func_name} docstring must explicitly say 'pass-through' — "
                f"downstream readers rely on this word to understand the contract."
            )
        assert family_pr in (func.__doc__ or ""), (
            f"{func_name} docstring must name {family_pr} as the family PR "
            f"that will replace this stub (or that already replaced it)."
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
    """For still-pass-through families, TODAY extended vote emitters return
    exactly what classic emitters return. For the trend family (bd-luy
    shipped), the contract relaxes to: extended is a superlist of classic
    (every classic vote is present + order preserved, plus new votes may
    be appended)."""

    def test_trend_votes_ext_is_superlist_of_classic(self, sample_panel):
        """bd-luy shipped: extended trend votes = classic votes + Aroon
        + Ichimoku (when panel keys are present)."""
        from openbb_techtrade.engine.confluence_ext import trend_votes_ext
        ext_votes = trend_votes_ext(sample_panel)
        classic_votes = confluence.trend_votes(sample_panel)
        # Classic votes must appear at the start in the same order.
        assert ext_votes[: len(classic_votes)] == classic_votes, (
            f"extended trend votes must start with the classic votes in order; "
            f"got ext={ [v.name for v in ext_votes] }, "
            f"classic={ [v.name for v in classic_votes] }"
        )

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
        "func_name,family_pr,expect_pass_through",
        [
            ("trend_votes_ext", "bd-luy", False),   # shipped
            ("momentum_votes_ext", "bd-40v", True),
            ("volatility_votes_ext", "bd-z43", True),
            ("_volume_votes_ext", "bd-alj", True),
        ],
    )
    def test_docstring_names_pass_through_and_family_pr(
        self, func_name, family_pr, expect_pass_through
    ):
        from openbb_techtrade.engine import confluence_ext
        func = getattr(confluence_ext, func_name)
        doc = (func.__doc__ or "").lower()
        if expect_pass_through:
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

    def test_extended_is_superset_of_classic_today(self, ohlcv_df):
        """bd-luy shipped: extended trend adds Aroon (and Ichimoku on
        >=78 bars). Contract is now SUBSET: every classic panel-key at
        every level is present in extended, plus extended adds new keys."""
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
        # Trend keys are extended; others still equal.
        assert set(classic.trend.keys()).issubset(set(extended.trend.keys()))
        assert classic.momentum == extended.momentum
        assert classic.volatility == extended.volatility
        assert classic.volume == extended.volume
        # Shared trend keys carry identical values.
        for k, v in classic.trend.items():
            assert extended.trend[k] == v, f"trend['{k}'] drifted"


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


class TestTechnicalPanelTechLegExtendedWarns:
    """bd-ie52 (PR #470 C2): the ORIGINAL version of this test injected
    ``SimpleNamespace(technical=None)`` and claimed to lock the tech-leg
    behavior, but ``technical=None`` causes an AttributeError on the
    first ``obb.technical.macd(...)`` call inside the try-block, which
    is caught and degrades to the classic fallback — so the test in fact
    exercised the fallback branch, not the tech-leg branch. Its R7.11
    claim (family PRs adding ``_compute_technical_*_ext`` would flip
    this red) was false: the code they'll modify was never reached.

    The R7.7-discriminating question is: "does this WARNING fire from
    the tech-leg code path, i.e., BEFORE the try-block that requires
    a real ``obb.technical`` namespace?" The answer is yes — line
    357-364 in ``indicators_technical.py`` emits the WARNING
    unconditionally when ``panel_config.panel == 'extended'``, no matter
    whether the subsequent try-block succeeds (family-PR wired) or
    fails (this-env wired). So the load-bearing behavior we can
    honestly test on this branch is:

    * The WARNING fires on the extended call.
    * The WARNING does NOT fire on the classic call.

    Mutation-verify: remove the ``if panel_config is not None and
    getattr(panel_config, "panel", None) == "extended"`` block and this
    test flips red (0 warnings observed).

    Family PRs (bd-luy landed; bd-40v/z43 pending) that wire
    ``_compute_technical_*_ext`` and remove this WARNING will
    intentionally break this test — that's the signal.
    """

    def test_tech_leg_extended_warns_but_classic_does_not(
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

        # Injected loader forces the tech branch (bypassing the
        # _obb_technical_available() env check). The subsequent try-block
        # will fail on the first obb.technical.* call and degrade to
        # classic — but by then the extended-WARNING has already fired
        # unconditionally at lines 357-364. That's the signal we assert
        # on (R7.9: caplog message > value assertion, since the value
        # ends up being the classic panel via degradation anyway).
        def fake_obb_loader():
            return SimpleNamespace(technical=None)

        # Extended call — must fire the WARNING
        with caplog.at_level(
            logging.WARNING,
            logger="openbb_techtrade.engine.indicators_technical",
        ):
            indicators_technical.technical_panel(
                symbol="TEST", as_of=as_of, ohlcv_rows=records,
                obb_loader=fake_obb_loader,
                panel_config=PANEL_EXTENDED,
            )
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

        # Classic call — must NOT fire that same WARNING (R7.7: without
        # this half of the assertion, a mutation that unconditionally
        # emits the WARNING regardless of panel_config would pass).
        caplog.clear()
        with caplog.at_level(
            logging.WARNING,
            logger="openbb_techtrade.engine.indicators_technical",
        ):
            indicators_technical.technical_panel(
                symbol="TEST", as_of=as_of, ohlcv_rows=records,
                obb_loader=fake_obb_loader,
                panel_config=PANEL_CLASSIC,
            )
        classic_extended_warnings = [
            r for r in caplog.records
            if "PANEL_EXTENDED requested" in r.getMessage()
        ]
        assert len(classic_extended_warnings) == 0, (
            f"PANEL_CLASSIC must not fire the extended-downgrade WARNING. "
            f"Got: {[r.getMessage() for r in caplog.records]}"
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
