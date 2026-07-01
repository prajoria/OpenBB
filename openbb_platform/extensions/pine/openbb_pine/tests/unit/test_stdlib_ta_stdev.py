"""Tests for ``openbb_pine.stdlib.ta.stdev`` — S-bead OpenBBTechnical-0e9.5.34 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.stdev`` (rolling standard deviation) variant.

Signature note: PyneCore's ``stdev(source, length, biased=True)`` computes
population standard deviation by default (``biased=True`` → variance
divided by ``n``, not ``n-1``). The Phase-1 stub only declared
``(src, length)``; Wave 5B-3 adds the third ``biased`` parameter so
keyword-form calls resolve. The default matches TradingView's Pine
reference — ``ta.stdev`` computes population stdev unless the caller
explicitly opts into unbiased.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "stdev"), "ta.stdev bridge missing"
        assert callable(ta.stdev)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "stdev" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.stdev"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_src_length_biased(self) -> None:
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.stdev")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length", "biased"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_stdev_default(self) -> None:
        """Bridge default matches PyneCore's ``biased=True`` (population stdev)."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.stdev") as mock_stdev:
            mock_stdev.return_value = 1.234
            result = _bridge.stdev("CLOSE", 20)
            mock_stdev.assert_called_once_with("CLOSE", 20, True)
            assert result == 1.234

    def test_calls_pynecore_ta_stdev_unbiased(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.stdev") as mock_stdev:
            mock_stdev.return_value = 1.5
            result = _bridge.stdev("CLOSE", 20, False)
            mock_stdev.assert_called_once_with("CLOSE", 20, False)
            assert result == 1.5


class TestCoverageManifest:
    def test_ta_stdev_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.stdev" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_stdev.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_stdev.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "stdev4" in rows[0]
        assert len(rows) >= 5
