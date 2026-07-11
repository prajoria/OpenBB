"""Tests for ``openbb_pine.stdlib.ta.highest`` — S-bead OpenBBTechnical-0e9.5.32 (Wave 5B-4).

See ``test_stdlib_ta_crossover.py`` for the bridge-shape contract rationale.
This test file is the ``ta.highest`` (rolling max) variant.

Signature note: PyneCore's ``ta.highest`` has a secondary single-arg
overload ``ta.highest(length)`` that defaults ``source`` to ``high``; the
bridge exposes only the explicit-source form. Wave 5B-4 flipped the stub's
first-arg name ``src`` → ``source`` to match PyneCore for keyword-form
calls.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "highest"), "ta.highest bridge missing"
        assert callable(ta.highest)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "highest" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.highest"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.highest")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_highest(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.highest") as mock_fn:
            mock_fn.return_value = 42.0
            result = _bridge.highest("CLOSE", 5)
            mock_fn.assert_called_once_with("CLOSE", 5)
            assert result == 42.0


class TestCoverageManifest:
    def test_ta_highest_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.highest" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_highest.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_highest.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "hi3" in rows[0]
        assert len(rows) >= 5
