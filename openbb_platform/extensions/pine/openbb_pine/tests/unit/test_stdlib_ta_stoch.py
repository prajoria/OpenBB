"""Tests for ``openbb_pine.stdlib.ta.stoch`` — S-bead OpenBBTechnical-0e9.5.24 (Wave 5B-2).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.stoch`` (Stochastic %K) variant. ``ta.stoch``
returns only the fast %K component; the %D signal line is a separate
``ta.sma(ta.stoch(...), 3)`` application in Pine.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "stoch"), "ta.stoch bridge missing"
        assert callable(ta.stoch)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "stoch" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.stoch"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_high_low_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.stoch")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "high", "low", "length"], (
            f"arg names drifted: {names}"
        )
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_stoch(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.stoch") as mock_stoch:
            mock_stoch.return_value = 75.0
            result = _bridge.stoch("CLOSE", "HIGH", "LOW", 14)
            mock_stoch.assert_called_once_with("CLOSE", "HIGH", "LOW", 14)
            assert result == 75.0


class TestCoverageManifest:
    def test_ta_stoch_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.stoch" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_stoch.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_stoch.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "stoch5" in rows[0]
        assert len(rows) >= 5
