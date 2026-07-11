"""Tests for ``openbb_pine.stdlib.ta.adx`` — S-bead OpenBBTechnical-0e9.5.26 (Wave 5B-2).

See ``test_stdlib_ta_sma.py`` for the bridge-shape contract rationale.
This test file is the ``ta.adx`` (Average Directional Index) variant.

Signature deviation from the rest of Wave 5B-2: PyneCore has NO standalone
``adx`` function — its module ``__all__`` only exports ``dmi``, which
returns a ``(+DI, -DI, ADX)`` triple. The bridge synthesises ``ta.adx``
by projecting ``dmi()[2]``. That is why:

* ``ta.adx`` is NOT one of the 29 PRD §3.2 Phase-1 ta.* builtins.
* Wave 5B-2 ADDED its :data:`BUILTIN_SIGNATURES` entry alongside the
  bridge — earlier waves did not need to touch it.
* The signature has no ``src`` parameter; ``ta.adx`` reads
  ``high``/``low`` transitively through ``ta.dmi``.

Delegation test therefore mocks ``pynecore.lib.ta.dmi`` (not ``adx``) and
asserts the bridge takes the third tuple element.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "adx"), "ta.adx bridge missing"
        assert callable(ta.adx)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "adx" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.adx"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_dilen_and_adxlen(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.adx")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["dilen", "adxlen"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_dmi_and_projects_third_element(self) -> None:
        """The bridge delegates to ``pynecore.lib.ta.dmi`` — NOT ``adx``,
        which does not exist in PyneCore's ``lib.ta`` — and returns the
        third tuple element (the ADX value)."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.dmi") as mock_dmi:
            mock_dmi.return_value = ("PLUS_DI", "MINUS_DI", 42.5)
            result = _bridge.adx(14, 14)
            mock_dmi.assert_called_once_with(14, 14)
            assert result == 42.5


class TestCoverageManifest:
    def test_ta_adx_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.adx" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_adx.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_adx.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "adx5" in rows[0]
        assert len(rows) >= 5
