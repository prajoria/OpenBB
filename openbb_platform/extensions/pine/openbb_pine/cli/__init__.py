"""Marker module — exposes the ``openbb-pine`` click CLI under ``openbb_pine.cli``.

The CLI entry point is registered in ``pyproject.toml`` as
``openbb-pine = "openbb_pine.cli.main:cli"``. After ``pip install -e .``,
the ``openbb-pine doctor`` and ``openbb-pine --version`` commands are real
shell scripts. The CLI implementation itself lives in :mod:`openbb_pine.cli.main`.
"""

from __future__ import annotations

__all__: list[str] = []
