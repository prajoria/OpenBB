"""Tests for ``openbb_pine.stdlib.ta.wma`` — S-bead OpenBBTechnical-0e9.5.18 (Wave 5B-1).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.wma`` (linear-weighted moving average) variant.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "wma"), "ta.wma bridge missing"
        assert callable(ta.wma)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "wma" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.wma"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.wma")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_wma(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.wma") as mock_wma:
            mock_wma.return_value = 99.9
            result = _bridge.wma("HIGH", 5)
            mock_wma.assert_called_once_with("HIGH", 5)
            assert result == 99.9


class TestCoverageManifest:
    def test_ta_wma_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.wma" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_wma.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_wma.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "wma3" in rows[0]
        assert len(rows) >= 5
