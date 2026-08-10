"""Unit tests for the cold-boot warmup auto-build disable + prime (#1962).

The #1957 warmup ran ``openbb.build()`` at lifespan startup, offloaded to an
anyio *worker* thread (``await anyio.to_thread.run_sync(_warm_openbb)``).
``openbb.build()`` calls ``signal.signal(signal.SIGTERM, ...)`` which raises
``ValueError: signal only works in main thread of the main interpreter`` on any
non-main thread. ``_warm_openbb`` swallowed that error, so the build silently
failed AND — worse — the build's delete-then-fail left the on-disk generated
package CORRUPTED, so every fresh backend served ``stub``.

Fix (#1962): the committed generated package already wires the live tier
providers and serves them WITHOUT any rebuild, so the backend disables openbb's
import-time ``auto_build`` (``OPENBB_AUTO_BUILD=false``, set at module load) and
the warmup merely *primes* the package (``import openbb`` + touch ``obb.equity``)
— a fast, main-thread-signal-free import. These tests pin that wiring and are
hermetic: they never import or build the real ``openbb`` package.
"""

from __future__ import annotations

import os

import pytest
from openbb_portfolio_intel.widget_backend import _app


def test_module_defines_openbb_auto_build() -> None:
    """Importing ``_app`` leaves ``OPENBB_AUTO_BUILD`` defined (#1962).

    openbb's ``__init__`` reads ``Env().AUTO_BUILD`` at import and rebuilds when
    it's truthy. The backend must have turned it off before openbb is ever
    imported so no boot-time rebuild (and no worker-thread ``signal`` corruption)
    can happen.
    """
    assert os.environ.get("OPENBB_AUTO_BUILD") is not None


def test_default_auto_build_off_defaults_to_false(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With no ambient override, the helper defaults auto-build to false.

    Reverse-verified: if the helper used ``os.environ[...] = "true"`` or dropped
    the call, this would observe ``None`` or ``"true"`` instead of ``"false"``.
    """
    monkeypatch.delenv("OPENBB_AUTO_BUILD", raising=False)

    _app._default_auto_build_off()

    assert os.environ.get("OPENBB_AUTO_BUILD") == "false"


def test_default_auto_build_off_respects_operator_override(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An explicit ``OPENBB_AUTO_BUILD`` is NOT clobbered by the helper."""
    monkeypatch.setenv("OPENBB_AUTO_BUILD", "true")

    _app._default_auto_build_off()

    assert os.environ["OPENBB_AUTO_BUILD"] == "true"


def test_default_builder_primes_without_building(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``_default_openbb_builder`` primes the package and never shells a build.

    Load-bearing: the pre-#1962 builder ran ``openbb.build()`` in a subprocess.
    The fixed builder must only prime — it delegates to ``_prime_openbb`` and
    nothing else.
    """
    calls: list[str] = []
    monkeypatch.setattr(_app, "_prime_openbb", lambda: calls.append("prime"))

    _app._default_openbb_builder()

    assert calls == ["prime"]


def test_app_module_has_no_subprocess_build() -> None:
    """The subprocess-build machinery is gone (#1962 pivot).

    Guards against a regression to the slow/corrupting boot-time rebuild: the
    module must expose neither the subprocess builder nor its imports.
    """
    assert not hasattr(_app, "_build_openbb_subprocess")
    assert not hasattr(_app, "subprocess")
    assert not hasattr(_app, "_OPENBB_BUILD_TIMEOUT_S")
