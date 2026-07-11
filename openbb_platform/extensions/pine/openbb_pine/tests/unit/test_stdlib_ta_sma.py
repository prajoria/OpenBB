"""Tests for ``openbb_pine.stdlib.ta.sma`` — S-bead OpenBBTechnical-0e9.5.16 (Wave 5B-1).

Bridge shape contract (D1 §3.1 + spec):

1. The bridge is importable at ``openbb_pine.stdlib.ta.sma``.
2. Its runtime effect is a one-line delegation to ``pynecore.lib.ta.sma``.
3. The compile-time signature at ``BUILTIN_SIGNATURES["ta.sma"]`` is
   ``(src: series<float>, length: simple<int>) -> series<float>`` and is
   marked ``notes="IMPLEMENTED"`` (the flip from ``"STUB"`` is what future
   readers grep for to reason about coverage state).
4. The identifier is present in
   :data:`openbb_pine._coverage_manifest.BUILTINS_IMPLEMENTED` so the L0.5
   wild-corpus coverage metric credits any script that touches it.
5. The conformance corpus at ``tests/conformance/ta_sma.{pine,csv}`` exists
   and is a well-formed pair the harness (X1 conftest) will auto-discover.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "sma"), "ta.sma bridge missing"
        assert callable(ta.sma)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "sma" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    """The compile-time signature is the C3 type-checker's contract.

    Bridge parameter names MUST agree with the registry — otherwise C3
    binds a kwarg to a name the bridge does not accept and the executor
    blows up at runtime with a TypeError far from the source.
    """

    def test_registry_entry_marked_implemented(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.sma"]
        assert sig.notes == "IMPLEMENTED", (
            f"expected notes='IMPLEMENTED', got {sig.notes!r}"
        )

    def test_signature_shape_src_and_length(self) -> None:
        from pyne_compiler.compiler.builtin_signatures import lookup
        from pyne_compiler.compiler.types import PineType, Scalar

        sig = lookup("ta.sma")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["src", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_sma(self) -> None:
        """The bridge must delegate — not reimplement — the numerics."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.sma") as mock_sma:
            mock_sma.return_value = 42.0
            result = _bridge.sma("SRC", 7)
            mock_sma.assert_called_once_with("SRC", 7)
            assert result == 42.0


class TestCoverageManifest:
    def test_ta_sma_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.sma" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    """The harness (X1) auto-discovers by walking ``tests/conformance/``
    for ``*.pine`` + sibling ``*.csv``. Both files must exist and be
    minimally well-formed so the harness can collect a test per pair.
    """

    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_sma.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_sma.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        # Header must include the plot column so the harness can diff it.
        assert "sma3" in rows[0]
        # At least (length-1) warm-up NA rows + a couple of value rows.
        assert len(rows) >= 5
