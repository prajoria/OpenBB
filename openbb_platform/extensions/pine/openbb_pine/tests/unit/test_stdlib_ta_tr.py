"""Tests for ``openbb_pine.stdlib.ta.tr`` — S-bead OpenBBTechnical-0e9.5.38 (Wave 5B-3).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.tr`` (True Range) variant.

Signature note: PyneCore models ``tr`` as a ``@module_property`` so both
``ta.tr`` (bare identifier) and ``ta.tr(handle_na)`` compile. The bridge
here exposes the callable form with default ``handle_na=False`` matching
PyneCore's signature; a Pine script writing ``plot(ta.tr)`` compiles via
codegen's zero-arg call insertion (Phase-2 concern) rather than the
bridge shape.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "tr"), "ta.tr bridge missing"
        assert callable(ta.tr)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "tr" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.tr"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_handle_na(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.tr")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["handle_na"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_tr_default(self) -> None:
        """Bridge default matches PyneCore's ``handle_na=False`` default."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.tr") as mock_tr:
            mock_tr.return_value = 2.5
            result = _bridge.tr()
            mock_tr.assert_called_once_with(False)
            assert result == 2.5

    def test_calls_pynecore_ta_tr_explicit(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.tr") as mock_tr:
            mock_tr.return_value = 1.75
            result = _bridge.tr(True)
            mock_tr.assert_called_once_with(True)
            assert result == 1.75


class TestCoverageManifest:
    def test_ta_tr_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.tr" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_tr.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_tr.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "tr" in rows[0]
        assert len(rows) >= 5
