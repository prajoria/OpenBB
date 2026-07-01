"""Tests for ``openbb_pine.stdlib.ta.bb`` — S-bead OpenBBTechnical-0e9.5.22 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.bb`` (Bollinger Bands) variant.

Signature note: ``ta.bb`` returns a 3-tuple ``(basis, upper, lower)`` — the
same tuple-return pattern as MACD (Wave 5B-1). The Phase-1 stub declared
its return as scalar ``series<float>``; Wave 5B-3 lifts it to a real
``TupleT`` of three ``series<float>`` elements so C3's tuple-destructuring
path can bind each of ``[basis, upper, lower]`` to its correct component
type. PyneCore's public signature is ``bb(source, length, mult)`` — the
C3 registry names them ``src``/``length``/``mult`` (Pine's shorter names);
positional dispatch keeps both sides interoperable — the bridge never
binds by name.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "bb"), "ta.bb bridge missing"
        assert callable(ta.bb)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "bb" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.bb"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_length_mult(self) -> None:
        from openbb_pine.compiler.builtin_signatures import lookup

        sig = lookup("ta.bb")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length", "mult"], f"arg names drifted: {names}"

    def test_signature_returns_tuple_of_three_series_float(self) -> None:
        """C3's tuple-destructuring reads TupleT.elements to route each of
        ``[basis, upper, lower]`` to the corresponding LHS binding."""
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar, TupleT

        sig = lookup("ta.bb")
        assert sig is not None
        inner = sig.returns.inner
        assert isinstance(inner, TupleT), (
            f"BB returns must be a TupleT, got {type(inner).__name__}"
        )
        assert len(inner.elements) == 3, (
            f"BB tuple arity != 3: {inner.elements}"
        )
        for i, el in enumerate(inner.elements):
            assert el == PineType(qualifier="series", inner=Scalar(kind="float")), (
                f"element {i} not series<float>: {el}"
            )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_bb(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.bb") as mock_bb:
            mock_bb.return_value = (102.0, 106.0, 98.0)
            result = _bridge.bb("CLOSE", 20, 2.0)
            mock_bb.assert_called_once_with("CLOSE", 20, 2.0)
            assert result == (102.0, 106.0, 98.0)


class TestCoverageManifest:
    def test_ta_bb_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.bb" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_bb.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_bb.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # BB emits three plot columns.
        assert "basis" in rows[0]
        assert "upper" in rows[0]
        assert "lower" in rows[0]
        assert len(rows) >= 5
