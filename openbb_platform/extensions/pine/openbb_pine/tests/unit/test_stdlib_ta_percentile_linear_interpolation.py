"""Tests for ``openbb_pine.stdlib.ta.percentile_linear_interpolation``
— S-bead OpenBBTechnical-0e9.5.42 (Wave 5B-4).

Signature deviation flagged: this builtin was NOT previously registered
in the Phase-1 stub table (PRD §3.2's 29 ta.* list did not enumerate it
explicitly). Wave 5B-4 adds the registry entry alongside the bridge.

Third arg is named ``percentage`` per PyneCore (NOT ``percentile`` as
some external references phrase it). ``percentage`` is on the 0..100
scale (Pine convention, not numpy's 0..1).
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "percentile_linear_interpolation"), (
            "ta.percentile_linear_interpolation bridge missing"
        )
        assert callable(ta.percentile_linear_interpolation)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "percentile_linear_interpolation" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.percentile_linear_interpolation"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_length_percentage(self) -> None:
        """PyneCore's third arg is named ``percentage`` (not ``percentile``);
        registry mirrors that so keyword-form calls resolve."""
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.percentile_linear_interpolation")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length", "percentage"], (
            f"arg names drifted: {names}"
        )
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_percentile_linear_interpolation(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch(
            "openbb_pine.stdlib.ta._pyne_ta.percentile_linear_interpolation"
        ) as mock_fn:
            mock_fn.return_value = 42.0
            result = _bridge.percentile_linear_interpolation("CLOSE", 10, 50)
            mock_fn.assert_called_once_with("CLOSE", 10, 50)
            assert result == 42.0


class TestCoverageManifest:
    def test_ta_percentile_linear_interpolation_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert (
            "ta.percentile_linear_interpolation"
            in _coverage_manifest.BUILTINS_IMPLEMENTED
        )


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_percentile_linear_interpolation.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_percentile_linear_interpolation.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "pct50" in rows[0]
        assert len(rows) >= 5
