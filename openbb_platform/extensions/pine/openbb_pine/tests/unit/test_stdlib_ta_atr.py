"""Tests for ``openbb_pine.stdlib.ta.atr`` — S-bead OpenBBTechnical-0e9.5.23 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.atr`` (Wilder's Average True Range) variant.

Signature note: ``ta.atr(length)`` takes NO source parameter — it reads
``high``/``low``/``close`` transitively through ``ta.tr`` and applies
Wilder's ``rma`` on top. That is why the Phase-1 stub was already
``args=(("length", _SIMPLE_INT),)``; Wave 5B-3 only flips the ``notes``
marker from ``"STUB"`` to ``"IMPLEMENTED"``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "atr"), "ta.atr bridge missing"
        assert callable(ta.atr)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "atr" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.atr"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_length_only(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.atr")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_atr(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.atr") as mock_atr:
            mock_atr.return_value = 3.14
            result = _bridge.atr(14)
            mock_atr.assert_called_once_with(14)
            assert result == 3.14


class TestCoverageManifest:
    def test_ta_atr_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.atr" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_atr.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_atr.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "atr3" in rows[0]
        assert len(rows) >= 5
