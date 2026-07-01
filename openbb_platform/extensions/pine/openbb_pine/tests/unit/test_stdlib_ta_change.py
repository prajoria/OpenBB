"""Tests for ``openbb_pine.stdlib.ta.change`` — S-bead OpenBBTechnical-0e9.5.35 (Wave 5B-4).

Signature deviation flagged: PyneCore's public signature is
``change(source, length=1)``. The Phase-1 stub had only ``src`` (missing
the trailing ``length``); Wave 5B-4 adds the ``length`` slot and flips
the first-arg name ``src`` → ``source``. The registry does not model
per-arg defaults — the ``length=1`` default lives in the bridge only;
C3's ``_check_call_args`` tolerates a missing trailing positional.
"""

from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch


class TestBridgeExists:
    def test_bridge_importable(self) -> None:
        from openbb_pine.stdlib import ta

        assert hasattr(ta, "change"), "ta.change bridge missing"
        assert callable(ta.change)

    def test_bridge_in_module_all(self) -> None:
        from openbb_pine.stdlib import ta

        assert "change" in ta.__all__


class TestBridgeSignatureRegistryMatch:
    def test_registry_entry_marked_implemented(self) -> None:
        from openbb_pine.compiler.builtin_signatures import BUILTIN_SIGNATURES

        sig = BUILTIN_SIGNATURES["ta.change"]
        assert sig.notes == "IMPLEMENTED"

    def test_signature_shape_source_and_length(self) -> None:
        """Wave 5B-4 lifts the stub from ``(src,)`` to
        ``(source, length)`` — length is optional at the bridge but the
        registry lists it so kwarg-form calls resolve.
        """
        from openbb_pine.compiler.builtin_signatures import lookup
        from openbb_pine.compiler.types import PineType, Scalar

        sig = lookup("ta.change")
        assert sig is not None
        names = [n for n, _ in sig.args]
        assert names == ["source", "length"], f"arg names drifted: {names}"
        assert sig.returns == PineType(
            qualifier="series", inner=Scalar(kind="float")
        )


class TestBridgeDelegates:
    def test_calls_pynecore_ta_change_with_default_length(self) -> None:
        """Default ``length=1`` lives at the bridge, not the registry."""
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.change") as mock_fn:
            mock_fn.return_value = 1.5
            result = _bridge.change("SRC")
            mock_fn.assert_called_once_with("SRC", 1)
            assert result == 1.5

    def test_calls_pynecore_ta_change_with_explicit_length(self) -> None:
        from openbb_pine.stdlib import ta as _bridge

        with patch("openbb_pine.stdlib.ta._pyne_ta.change") as mock_fn:
            mock_fn.return_value = -2.0
            result = _bridge.change("SRC", 5)
            mock_fn.assert_called_once_with("SRC", 5)
            assert result == -2.0


class TestCoverageManifest:
    def test_ta_change_in_implemented_manifest(self) -> None:
        from openbb_pine import _coverage_manifest

        assert "ta.change" in _coverage_manifest.BUILTINS_IMPLEMENTED


class TestConformancePairPresent:
    _ROOT = Path(__file__).resolve().parents[6] / "tests" / "conformance"

    def test_pine_fixture_exists(self) -> None:
        assert (self._ROOT / "ta_change.pine").is_file()

    def test_csv_fixture_exists_and_parses(self) -> None:
        csv_path = self._ROOT / "ta_change.csv"
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))
        assert "chg1" in rows[0]
        assert len(rows) >= 5
