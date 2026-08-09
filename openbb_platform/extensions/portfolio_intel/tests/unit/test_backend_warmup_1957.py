"""Unit tests for the cold-boot openbb warmup (#1957).

A freshly-started backend whose generated ``openbb`` package is not yet built
serves ``stub`` for every live-wired widget: the first live tier call triggers
a multi-second ``openbb.build()`` inside the request, the ChainedFetcher
exhausts before it finishes, and the endpoint falls back to the demo stub.
:func:`_warm_openbb` builds/primes the package in lifespan startup so the first
real request finds a built package and serves live.

These tests are hermetic — they inject a fake builder and never import or
build the real ``openbb`` package.
"""

from __future__ import annotations

import logging

import pytest

from openbb_portfolio_intel.widget_backend import _app


def test_warm_openbb_invokes_builder() -> None:
    """The injected builder is called exactly once (the build actually runs)."""
    calls: list[int] = []

    def fake_builder() -> None:
        calls.append(1)

    _app._warm_openbb(builder=fake_builder)

    assert calls == [1]


def test_warm_openbb_swallows_builder_error(caplog: pytest.LogCaptureFixture) -> None:
    """A build failure is logged and swallowed — startup must never die on it."""

    def exploding_builder() -> None:
        raise RuntimeError("simulated build failure")

    with caplog.at_level(
        logging.WARNING, logger="openbb_portfolio_intel.widget_backend._app"
    ):
        # Must NOT raise.
        _app._warm_openbb(builder=exploding_builder)

    warnings = [r for r in caplog.records if "openbb warmup" in r.getMessage()]
    assert len(warnings) == 1, "expected exactly one swallowed-failure WARNING"


def test_warm_openbb_skips_when_env_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``PI_WIDGET_BACKEND_SKIP_WARMUP`` short-circuits — builder never runs."""
    monkeypatch.setenv("PI_WIDGET_BACKEND_SKIP_WARMUP", "1")
    calls: list[int] = []

    def fake_builder() -> None:  # pragma: no cover - must not be called
        calls.append(1)

    _app._warm_openbb(builder=fake_builder)

    assert calls == [], "warmup must not build when the skip env is set"


def test_warm_openbb_runs_when_env_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the skip env absent, the injected builder runs (guards the gate)."""
    monkeypatch.delenv("PI_WIDGET_BACKEND_SKIP_WARMUP", raising=False)
    calls: list[int] = []

    _app._warm_openbb(builder=lambda: calls.append(1))

    assert calls == [1]


def test_lifespan_warms_before_registering_probers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifespan startup calls the warmup (offloaded to a thread) before yield.

    Guards the wiring: if the ``await anyio.to_thread.run_sync(_warm_openbb)``
    line is dropped, this fails because the warmup sentinel never fires.
    """
    import anyio

    order: list[str] = []

    monkeypatch.setattr(_app, "_warm_openbb", lambda: order.append("warm"))
    monkeypatch.setattr(_app, "_register_health_probers", lambda: order.append("probe"))

    async def drive() -> None:
        async with _app._lifespan(_app.app):
            order.append("serving")

    anyio.run(drive)

    assert order[:3] == ["warm", "probe", "serving"], order
