"""Tests for ``openbb_pine.stdlib.ta.mom`` — S-bead OpenBBTechnical-0e9.5.36 (Wave 5B-4).

Semantically identical to ``ta.change`` with explicit length. PyneCore's
``ta.mom`` is literally a one-line delegation to ``ta.change``
(``ta.py:1068``); we still bridge it as a distinct name so the type
checker's registry lookup and the wild-corpus coverage metric both
recognise a script that uses ``ta.mom``.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "mom"), "ta.mom bridge missing"
        assert callable(ta.mom)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "mom" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.mom"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.mom")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_mom(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.mom") as mock_fn:
            mock_fn.return_value = 2.5
            result = _bridge.mom("CLOSE", 4)
            mock_fn.assert_called_once_with("CLOSE", 4)
            assert result == 2.5


class TestCoverageManifest:
    def test_ta_mom_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.mom" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_mom.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_mom.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "mom3" in rows[0]
        assert len(rows) >= 5
