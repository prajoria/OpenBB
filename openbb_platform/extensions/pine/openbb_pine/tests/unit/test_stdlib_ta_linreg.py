"""Tests for ``openbb_pine.stdlib.ta.linreg`` — S-bead OpenBBTechnical-0e9.5.40 (Wave 5B-4).

Signature deviation flagged: PyneCore's ``ta.linreg(source, length, offset)``
declares ``offset`` REQUIRED (no default) — matching both the PyneCore
implementation and the Pine reference manual. Common call is
``ta.linreg(source, length, 0)`` for the current-bar value. Wave 5B-4
flips the stub's first-arg name from ``src`` → ``source``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "linreg"), "ta.linreg bridge missing"
        assert callable(ta.linreg)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "linreg" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.linreg"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_length_offset(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.linreg")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length", "offset"], (
            f"arg names drifted: {names}"
        )
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_linreg(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.linreg") as mock_fn:
            mock_fn.return_value = 100.0
            result = _bridge.linreg("CLOSE", 14, 0)
            mock_fn.assert_called_once_with("CLOSE", 14, 0)
            assert result == 100.0


class TestCoverageManifest:
    def test_ta_linreg_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.linreg" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_linreg.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_linreg.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "linreg5" in rows[0]
        assert len(rows) >= 5
