"""Tests for ``openbb_pine.stdlib.ta.macd`` — S-bead OpenBBTechnical-0e9.5.21 (Wave 5B-1).

MACD is the only Wave-5B-1 builtin whose return type is a tuple. The
Phase-1 stub declared it as ``series<float>`` (a scalar simplification);
Wave 5B-1 lifted that to a real ``TupleT`` of three ``series<float>``
elements so the C3 type-checker's tuple-destructuring path can bind each
of ``[macd_line, signal_line, hist_line]`` to its correct component type.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "macd"), "ta.macd bridge missing"
        assert callable(ta.macd)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "macd" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.macd"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_fastlen_slowlen_siglen(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup

        sig = lookup("ta.macd")
        assert sig is not None
        names = [n for n, _ in sig.args]
        # Order matches PyneCore's positional convention.
        assert names == ["src", "fastlen", "slowlen", "siglen"], (
            f"arg names drifted: {names}"
        )

    def test_signature_returns_tuple_of_three_series_float(self) -> None:
        """C3's tuple-destructuring reads TupleT.elements to route each
        of ``[line, signal, hist]`` to the corresponding LHS binding —
        this test fixes the tuple arity + element shape."""
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar, TupleT

        sig = lookup("ta.macd")
        assert sig is not None
        inner = sig.returns.inner
        assert isinstance(inner, TupleT), (
            f"MACD returns must be a TupleT, got {type(inner).__name__}"
        )
        assert len(inner.elements) == 3, (
            f"MACD tuple arity != 3: {inner.elements}"
        )
        for i, el in enumerate(inner.elements):
            assert el == PineType(qualifier="series", inner=Scalar(kind="float")), (
                f"element {i} not series<float>: {el}"
            )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_macd(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.macd") as mock_macd:
            mock_macd.return_value = (1.0, 2.0, -1.0)
            result = _bridge.macd("CLOSE", 12, 26, 9)
            mock_macd.assert_called_once_with("CLOSE", 12, 26, 9)
            assert result == (1.0, 2.0, -1.0)


class TestCoverageManifest:
    def test_ta_macd_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.macd" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_macd.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_macd.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # MACD emits three plot columns.
        assert "macd" in rows[0]
        assert "signal" in rows[0]
        assert "hist" in rows[0]
        assert len(rows) >= 5
