"""Tests for ``openbb_pine.stdlib.ta.mfi`` — S-bead OpenBBTechnical-0e9.5.27 (Wave 5B-2).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.mfi`` (Money Flow Index) variant.

Note: ``ta.mfi`` reads ``volume`` from the primary OHLCV stream in addition
to its ``source`` argument. The BYODataProvider validates that ``volume``
is present up front (see openbb_pine.runtime.byo_provider), so any
missing-volume input fails fast well before the bridge is called.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "mfi"), "ta.mfi bridge missing"
        assert callable(ta.mfi)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "mfi" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.mfi"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.mfi")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_mfi(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.mfi") as mock_mfi:
            mock_mfi.return_value = 63.2
            result = _bridge.mfi("HLC3", 14)
            mock_mfi.assert_called_once_with("HLC3", 14)
            assert result == 63.2


class TestCoverageManifest:
    def test_ta_mfi_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.mfi" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_mfi.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_mfi.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "mfi5" in rows[0]
        assert len(rows) >= 5
