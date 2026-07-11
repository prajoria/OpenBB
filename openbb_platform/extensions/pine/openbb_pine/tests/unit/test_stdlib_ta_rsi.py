"""Tests for ``openbb_pine.stdlib.ta.rsi`` — S-bead OpenBBTechnical-0e9.5.20 (Wave 5B-2).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.rsi`` (Relative Strength Index) variant.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "rsi"), "ta.rsi bridge missing"
        assert callable(ta.rsi)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "rsi" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.rsi"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.rsi")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_rsi(self) -> None:
        """The bridge must delegate — not reimplement — the numerics."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.rsi") as mock_rsi:
            mock_rsi.return_value = 55.5
            result = _bridge.rsi("CLOSE", 14)
            mock_rsi.assert_called_once_with("CLOSE", 14)
            assert result == 55.5


class TestCoverageManifest:
    def test_ta_rsi_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.rsi" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_rsi.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_rsi.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # Header must include the plot column so the harness can diff it.
        assert "rsi3" in rows[0]
        # At least (length) warm-up NA rows + a couple of value rows.
        assert len(rows) >= 5
