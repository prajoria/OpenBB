"""Tests for ``openbb_pine.stdlib.ta.obv`` — S-bead OpenBBTechnical-0e9.5.28 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.obv`` (On-Balance Volume) variant.

Signature note: ``ta.obv`` is NOT in the 29 PRD §3.2 Phase-1 ta.* builtin
list, and PyneCore models it as a zero-arg ``@module_property`` — a Pine
script uses ``ta.obv`` as a bare identifier (e.g. ``plot(ta.obv)``) which
Pine's expression-vs-call machinery resolves to a value. Wave 5B-3 ADDS
its :data:`BUILTIN_SIGNATURES` entry alongside the bridge because C3 would
otherwise raise ``PineUnsupportedBuiltinError`` on the identifier — the
Phase-1 stub only carried the 29 named entries.

The bridge is exposed as a plain zero-arg callable ``ta.obv()`` so
downstream codegen has a uniform "call the bridge" shape; the compile
signature declares ``args=()`` matching that call site.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "obv"), "ta.obv bridge missing"
        assert callable(ta.obv)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "obv" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.obv"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_zero_arg(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.obv")
        assert sig is not None
        assert sig.args == (), f"ta.obv should have no args, got: {sig.args}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_obv(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.obv") as mock_obv:
            mock_obv.return_value = 12345.0
            result = _bridge.obv()
            mock_obv.assert_called_once_with()
            assert result == 12345.0


class TestCoverageManifest:
    def test_ta_obv_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.obv" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_obv.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_obv.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "obv" in rows[0]
        assert len(rows) >= 5
