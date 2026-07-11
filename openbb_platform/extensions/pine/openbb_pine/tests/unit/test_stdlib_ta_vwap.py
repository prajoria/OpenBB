"""Tests for ``openbb_pine.stdlib.ta.vwap`` — S-bead OpenBBTechnical-0e9.5.29 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.vwap`` (Volume-Weighted Average Price) variant.

Signature note: PyneCore's ``vwap(source, anchor=None, stdev_mult=None)``
has three parameters. The two-return-shape (scalar vs 3-tuple when
``stdev_mult`` is set) is a runtime concern — the C3 stub declares the
scalar ``series<float>`` return because the vast majority of Pine scripts
call ``ta.vwap(hlc3)`` or ``ta.vwap(close)`` without the stdev-bands
overload. Scripts using the bands form will need a future signature
lift; the bridge itself already accepts and forwards ``stdev_mult`` so no
bridge change is required at that point.

Wave 5B-3 ADDS the ``ta.vwap`` registry entry because it is NOT one of
the 29 PRD §3.2 Phase-1 ta.* builtins. Anchor semantics: ``anchor=None``
lets PyneCore default to ``session.isfirstbar``. Our conformance fixture
passes an explicit ``bar_index == 0`` anchor so the single-session
cumulative TPV/Vol path is exercised in the synthetic dataset.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "vwap"), "ta.vwap bridge missing"
        assert callable(ta.vwap)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "vwap" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.vwap"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_anchor_stdev_mult(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.vwap")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "anchor", "stdev_mult"], (
            f"arg names drifted: {names}"
        )
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_vwap_default_anchor(self) -> None:
        """Bridge default anchor=None passes through to PyneCore which
        falls back to ``session.isfirstbar``."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.vwap") as mock_vwap:
            mock_vwap.return_value = 100.5
            result = _bridge.vwap("HLC3")
            mock_vwap.assert_called_once_with("HLC3", None, None)
            assert result == 100.5

    def test_calls_pynecore_ta_vwap_with_anchor(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.vwap") as mock_vwap:
            mock_vwap.return_value = 101.0
            result = _bridge.vwap("CLOSE", True)
            mock_vwap.assert_called_once_with("CLOSE", True, None)
            assert result == 101.0


class TestCoverageManifest:
    def test_ta_vwap_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.vwap" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_vwap.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_vwap.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "vwap" in rows[0]
        assert len(rows) >= 5
