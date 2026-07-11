"""Tests for ``openbb_pine.stdlib.ta.crossunder`` — S-bead OpenBBTechnical-0e9.5.31 (Wave 5B-4).

See ``test_stdlib_ta_crossover.py`` for the bridge-shape contract rationale.
This test file is the ``ta.crossunder`` variant — symmetric to crossover,
identical shape.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "crossunder"), "ta.crossunder bridge missing"
        assert callable(ta.crossunder)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "crossunder" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.crossunder"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source1_source2(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.crossunder")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source1", "source2"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="bool")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_crossunder(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.crossunder") as mock_fn:
            mock_fn.return_value = False
            result = _bridge.crossunder("S1", "S2")
            mock_fn.assert_called_once_with("S1", "S2")
            assert result is False


class TestCoverageManifest:
    def test_ta_crossunder_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.crossunder" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_crossunder.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_crossunder.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "cu" in rows[0]
        assert len(rows) >= 5
