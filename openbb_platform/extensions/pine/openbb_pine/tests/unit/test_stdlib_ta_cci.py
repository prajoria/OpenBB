"""Tests for ``openbb_pine.stdlib.ta.cci`` — S-bead OpenBBTechnical-0e9.5.25 (Wave 5B-2).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.cci`` (Commodity Channel Index) variant.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "cci"), "ta.cci bridge missing"
        assert callable(ta.cci)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "cci" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.cci"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_and_length(self) -> None:
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.cci")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_cci(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.cci") as mock_cci:
            mock_cci.return_value = -105.0
            result = _bridge.cci("HL2", 20)
            mock_cci.assert_called_once_with("HL2", 20)
            assert result == -105.0


class TestCoverageManifest:
    def test_ta_cci_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.cci" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_cci.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_cci.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "cci5" in rows[0]
        assert len(rows) >= 5
