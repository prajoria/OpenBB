"""Tests for ``openbb_pine.stdlib.ta.cum`` — S-bead OpenBBTechnical-0e9.5.43 (Wave 5B-4).

``ta.cum`` has NO ``length`` argument — it accumulates from the first
bar. No warmup phase; the first bar equals the first source value.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "cum"), "ta.cum bridge missing"
        assert callable(ta.cum)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "cum" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.cum"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_only_no_length(self) -> None:
        """cum is the one Wave 5B-4 builtin without ``length`` — the sig
        must reflect that so kwarg-form callers can't accidentally pass a
        length that the bridge would silently ignore."""
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.cum")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_cum(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.cum") as mock_fn:
            mock_fn.return_value = 999.99
            result = _bridge.cum("VOL")
            mock_fn.assert_called_once_with("VOL")
            assert result == 999.99


class TestCoverageManifest:
    def test_ta_cum_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.cum" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_cum.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_cum.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "cum" in rows[0]
        assert len(rows) >= 5
