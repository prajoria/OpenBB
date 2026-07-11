"""Tests for ``openbb_pine.stdlib.ta.median`` — S-bead OpenBBTechnical-0e9.5.41 (Wave 5B-4).

Rolling median via PyneCore's two-heap implementation. ``length == 1``
is a short-circuit that returns ``source`` unchanged.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "median"), "ta.median bridge missing"
        assert callable(ta.median)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "median" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.median"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.median")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_median(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.median") as mock_fn:
            mock_fn.return_value = 50.0
            result = _bridge.median("CLOSE", 9)
            mock_fn.assert_called_once_with("CLOSE", 9)
            assert result == 50.0


class TestCoverageManifest:
    def test_ta_median_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.median" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_median.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_median.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "med3" in rows[0]
        assert len(rows) >= 5
