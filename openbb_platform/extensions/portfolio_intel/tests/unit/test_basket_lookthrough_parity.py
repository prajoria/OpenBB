"""Notebook parity for the basket analytics engine (#2313).

The oracle is the notebook itself: each test executes the reviewed code
cell from ``notebooks/portfolio/03-basket-xray-and-risk.ipynb`` with its
rendering helpers stubbed out, then compares the cell's variables with the
engine's answer on the same synthetic inputs. If either side changes its
math, the test fails.
"""

# The oracle is the notebook's own code, so these tests exec its cells; the
# fake providers mirror the Platform signatures they replace.
# pylint: disable=exec-used,unused-argument,import-outside-toplevel

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest
from openbb_portfolio_intel.analytics.basket_lookthrough import (
    basket_sector_view,
    concentration,
    construction_targets,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
NOTEBOOK_DIR = REPO_ROOT / "notebooks" / "portfolio"
NOTEBOOK = NOTEBOOK_DIR / "03-basket-xray-and-risk.ipynb"

pytestmark = pytest.mark.skipif(
    not NOTEBOOK.is_file(), reason="portfolio notebooks are not in this checkout"
)


def _cell(marker: str, *, compute_only: bool = False) -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    matches = [
        "".join(c["source"])
        for c in cells
        if c["cell_type"] == "code" and marker in "".join(c["source"])
    ]
    assert len(matches) == 1, f"expected one cell tagged {marker!r}"
    # The render block only formats variables the compute block produced.
    return matches[0].split("# --- render")[0] if compute_only else matches[0]


def _render_stubs() -> dict:
    return {
        "nb_panel": lambda *a, **k: None,
        "nb_pill": lambda *a, **k: "",
        "nb_table": lambda *a, **k: "",
    }


# A synthetic book: a few heavy names so both caps bind, a long thin tail.
EFFECTIVE = {"N00": 0.11, "N01": 0.09, "N02": 0.07, "N03": 0.065, "N04": 0.05}
EFFECTIVE.update({f"T{i:02d}": 0.012 for i in range(50)})
BASKET = [{"symbol": "AAA", "weight": 0.6}, {"symbol": "BBB", "weight": 0.4}]


def test_hhi_and_effective_n_match_notebook_section_5() -> None:
    """Raw and x-ray HHI and effective-N match §5."""
    namespace = {"basket": BASKET, "effective": EFFECTIVE, **_render_stubs()}
    exec(_cell("[Phase B / NB03 §5]"), namespace)  # noqa: S102
    raw = concentration({p["symbol"]: p["weight"] for p in BASKET})
    xray = concentration(EFFECTIVE)
    assert raw.hhi == pytest.approx(namespace["hhi_raw"])
    assert raw.effective_n == pytest.approx(namespace["neff_raw"])
    assert xray.hhi == pytest.approx(namespace["hhi_xray"])
    assert xray.effective_n == pytest.approx(namespace["neff_xray"])


def test_top_k_and_kill_shot_match_notebook_section_7() -> None:
    """Top-K weights and the kill shot match §7."""
    namespace = {
        "effective": EFFECTIVE,
        "hhi_xray": 0.0,
        "neff_xray": 0.0,
        **_render_stubs(),
    }
    exec(_cell("[Phase B / NB03 §7]"), namespace)  # noqa: S102
    result = concentration(EFFECTIVE)
    assert result.top1 == pytest.approx(namespace["top1"])
    assert result.top5 == pytest.approx(namespace["top5"])
    assert result.top10 == pytest.approx(namespace["top10"])
    assert result.largest == namespace["top_sym"]
    assert result.kill_shot == pytest.approx(namespace["kill_shot_pct"])


@pytest.mark.parametrize("scale", [1.0, 0.5])
def test_construction_matches_notebook_section_8(scale: float) -> None:
    """Targets, statuses, residual and capped count match §8."""
    effective = {k: v * scale for k, v in EFFECTIVE.items()}
    namespace = {
        "effective": effective,
        "basket": BASKET,
        "non_nport": [],
        "unknown_count": 0,
        **_render_stubs(),
    }
    exec(_cell("[Phase B / NB03 §8]"), namespace)  # noqa: S102
    result = construction_targets(effective)
    expected = namespace["construction_targets"]
    if expected is None:
        assert result.refused and result.targets is None
        return
    assert not result.refused
    assert result.targets.keys() == expected.keys()
    for name, row in expected.items():
        assert result.targets[name] == pytest.approx(row), name
        assert result.targets[name]["status"] == row["status"], name
    assert result.residual == pytest.approx(namespace["_residual"])
    assert result.capped_names == namespace["_over"]


def test_sector_view_matches_notebook_section_4(tmp_path, monkeypatch) -> None:
    """The look-through sector view matches §4."""
    holdings = {
        "QQQ": [
            {
                "name": "Alpha Corp",
                "symbol": None,
                "weight": 0.5,
                "asset_category": "EC",
            },
            {"name": "Beta Inc", "symbol": None, "weight": 0.3, "asset_category": "EC"},
            {
                "name": "Short Fund",
                "symbol": None,
                "weight": 0.2,
                "asset_category": "STIV",
            },
        ],
    }
    cache = tmp_path / ".notebook_state" / "nport_cache"
    cache.mkdir(parents=True)
    for symbol, rows in holdings.items():
        (cache / f"holdings_{symbol}.json").write_text(json.dumps(rows))
    tickers = {"Alpha Corp": "ALP", "Beta Inc": "BET"}
    sectors = {"ALP": "Technology", "BET": "Health Care", "MSFT": "Technology"}

    def _search(query, provider):
        hit = tickers.get(query)
        return SimpleNamespace(results=[SimpleNamespace(symbol=hit)] if hit else [])

    def _profile(symbol, provider):
        return SimpleNamespace(results=[SimpleNamespace(sector=sectors.get(symbol))])

    def _nport(symbol, provider):
        raise RuntimeError(f"No N-Port records found for {symbol}")

    fake = ModuleType("openbb")
    fake.obb = SimpleNamespace(
        equity=SimpleNamespace(search=_search, profile=_profile),
        etf=SimpleNamespace(nport_disclosure=_nport),
    )
    monkeypatch.setitem(sys.modules, "openbb", fake)
    monkeypatch.syspath_prepend(str(NOTEBOOK_DIR))
    monkeypatch.chdir(tmp_path)
    basket = [
        {"symbol": "QQQ", "weight": 0.4},
        {"symbol": "VWO", "weight": 0.1},  # equity ETF without a filing
        {"symbol": "BND", "weight": 0.2},
        {"symbol": "GLD", "weight": 0.1},
        {"symbol": "MSFT", "weight": 0.2},
    ]
    namespace = {"basket": basket, **_render_stubs()}
    exec(_cell("[Phase B / NB03 §4]", compute_only=True), namespace)  # noqa: S102

    def _holdings_for(symbol):
        from _nport_lookthrough import nport_holdings  # noqa: PLC0415

        return nport_holdings(symbol)

    view = basket_sector_view(
        basket,
        holdings_for=_holdings_for,
        sector_for_name=lambda name: sectors.get(tickers.get(name, "")),
        sector_for_symbol=sectors.get,
        equity_etfs=namespace["EQUITY_ETFS"],
        bond_etfs=namespace["BOND_ETFS"],
        commodity_trusts=namespace["COMMODITY_TRUSTS"],
        top_n_resolve=30,
    )
    assert view.sectors == pytest.approx(namespace["xray_by_sector"])
    assert view.unknown_count == namespace["unknown_count"]
