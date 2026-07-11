"""Tests for ``openbb_pine.stdlib.ta.sar`` — S-bead OpenBBTechnical-0e9.5.39 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.sar`` (Parabolic SAR — Stop and Reverse) variant.

Signature note: PyneCore's ``sar(start=0.02, inc=0.02, max=0.2)`` takes
NO source parameter — the SAR algorithm reads ``high`` / ``low`` directly
from the OHLCV stream to detect trend reversals. All three parameters
have Wilder's original defaults; a script calling ``ta.sar()`` unparenned
uses the same defaults. The parameter named ``max`` shadows Python's
builtin — PyneCore silences the shadow warning; the bridge preserves the
name so keyword-form calls resolve.

Wave 5B-3 ADDS the ``ta.sar`` registry entry because it is NOT one of
the 29 PRD §3.2 Phase-1 ta.* builtins.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "sar"), "ta.sar bridge missing"
        assert callable(ta.sar)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "sar" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.sar"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_start_inc_max(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.sar")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["start", "inc", "max"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_sar_defaults(self) -> None:
        """Bridge defaults mirror PyneCore's Wilder defaults 0.02/0.02/0.2."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.sar") as mock_sar:
            mock_sar.return_value = 99.5
            result = _bridge.sar()
            mock_sar.assert_called_once_with(0.02, 0.02, 0.2)
            assert result == 99.5

    def test_calls_pynecore_ta_sar_explicit(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.sar") as mock_sar:
            mock_sar.return_value = 101.25
            result = _bridge.sar(0.05, 0.05, 0.5)
            mock_sar.assert_called_once_with(0.05, 0.05, 0.5)
            assert result == 101.25


class TestCoverageManifest:
    def test_ta_sar_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.sar" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_sar.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_sar.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "sar" in rows[0]
        assert len(rows) >= 5
