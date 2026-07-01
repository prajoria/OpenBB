"""Tests for ``openbb_pine.stdlib.ta.rma`` — S-bead OpenBBTechnical-0e9.5.19 (Wave 5B-1).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.rma`` (Wilder's smoothing) variant.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "rma"), "ta.rma bridge missing"
        assert callable(ta.rma)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "rma" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.rma"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_and_length(self) -> None:
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.rma")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_rma(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.rma") as mock_rma:
            mock_rma.return_value = 3.14
            result = _bridge.rma("LOW", 14)
            mock_rma.assert_called_once_with("LOW", 14)
            assert result == 3.14


class TestCoverageManifest:
    def test_ta_rma_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.rma" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_rma.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_rma.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "rma3" in rows[0]
        assert len(rows) >= 5
