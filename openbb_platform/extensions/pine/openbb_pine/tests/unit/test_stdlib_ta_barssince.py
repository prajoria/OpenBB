"""Tests for ``openbb_pine.stdlib.ta.barssince`` — S-bead OpenBBTechnical-0e9.5.44 (Wave 5B-4).

Signature deviation flagged: PyneCore names the arg ``condition``; the
Phase-1 stub previously used ``cond``. Wave 5B-4 flips to the PyneCore
name so keyword-form calls resolve through the bridge.

Return: ``series<int>``. PyneCore returns ``NA(int)`` sentinel until
``condition`` has been true at least once (stored persistent counter
== ``-1`` sentinel state), non-NA int thereafter.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "barssince"), "ta.barssince bridge missing"
        assert callable(ta.barssince)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "barssince" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.barssince"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_condition_only(self) -> None:
        """Wave 5B-4 flipped the arg name ``cond`` → ``condition`` to
        match PyneCore, so keyword-form calls resolve."""
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.barssince")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["condition"], f"arg names drifted: {names}"
        # Return is series<int> — the counter is integer-valued.
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="int")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_barssince(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.barssince") as mock_fn:
            mock_fn.return_value = 3
            result = _bridge.barssince("COND")
            mock_fn.assert_called_once_with("COND")
            assert result == 3


class TestCoverageManifest:
    def test_ta_barssince_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.barssince" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_barssince.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_barssince.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "bs107" in rows[0]
        assert len(rows) >= 5
