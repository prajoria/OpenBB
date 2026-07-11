"""Tests for ``openbb_pine.stdlib.ta.lowest`` — S-bead OpenBBTechnical-0e9.5.33 (Wave 5B-4).

See ``test_stdlib_ta_highest.py`` for the shape rationale; ``ta.lowest``
is symmetric to ``ta.highest`` in every dimension.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "lowest"), "ta.lowest bridge missing"
        assert callable(ta.lowest)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "lowest" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.lowest"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.lowest")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_lowest(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.lowest") as mock_fn:
            mock_fn.return_value = 3.14
            result = _bridge.lowest("HIGH", 7)
            mock_fn.assert_called_once_with("HIGH", 7)
            assert result == 3.14


class TestCoverageManifest:
    def test_ta_lowest_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.lowest" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_lowest.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_lowest.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "lo3" in rows[0]
        assert len(rows) >= 5
