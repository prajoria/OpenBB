"""Tests for ``openbb_pine.stdlib.ta.crossover`` — S-bead OpenBBTechnical-0e9.5.30 (Wave 5B-4).

Bridge shape contract (D1 §3.1 + spec):

1. The bridge is importable at ``openbb_pine.stdlib.ta.crossover``.
2. Its runtime effect is a one-line delegation to ``pynecore.lib.ta.crossover``.
3. The compile-time signature at ``BUILTIN_SIGNATURES["ta.crossover"]`` is
   ``(source1: series<float>, source2: series<float>) -> series<bool>`` and
   is marked ``notes="IMPLEMENTED"``.
4. The identifier is present in
   :data:`openbb_pine._coverage_manifest.BUILTINS_IMPLEMENTED` so the L0.5
   wild-corpus coverage metric credits any script that touches it.
5. The conformance corpus at ``tests/conformance/ta_crossover.{pine,csv}``
   exists and is a well-formed pair the harness (X1 conftest) will
   auto-discover.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "crossover"), "ta.crossover bridge missing"
        assert callable(ta.crossover)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "crossover" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.crossover"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source1_source2(self) -> None:
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.crossover")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source1", "source2"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="bool")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_crossover(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.crossover") as mock_fn:
            mock_fn.return_value = True
            result = _bridge.crossover("S1", "S2")
            mock_fn.assert_called_once_with("S1", "S2")
            assert result is True


class TestCoverageManifest:
    def test_ta_crossover_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.crossover" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_crossover.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_crossover.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "co" in rows[0]
        assert len(rows) >= 5
