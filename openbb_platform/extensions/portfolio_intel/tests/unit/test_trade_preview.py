"""Candidate trades and weight-space what-if diffs (#2315, N05c).

Hand-computed expectations, plus notebook parity: the reviewed cells of
``notebooks/portfolio/05-whatif-attribution-and-paper.ipynb`` are executed
with rendering stubbed out, and their variables are the oracle.
"""

# The oracle is the notebook's own code, so these tests exec its cells.
# pylint: disable=exec-used,unused-argument

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pandas as pd
import pytest
from openbb_portfolio_intel.analytics.trade_preview import (
    candidate_trades,
    whatif_weight_diff,
)

REPO_ROOT = Path(__file__).resolve().parents[5]
NOTEBOOK = (
    REPO_ROOT / "notebooks" / "portfolio" / "05-whatif-attribution-and-paper.ipynb"
)
CONVICTION = [
    {"symbol": "MSFT", "composite": 0.72, "signal_count": 6},
    {"symbol": "NVDA", "composite": 0.61, "signal_count": 5},
    {"symbol": "AMD", "composite": -0.58, "signal_count": 4},
    {"symbol": "XOM", "composite": 0.10, "signal_count": 1},
]
BASKET = [
    {"symbol": "MSFT", "weight": 0.4},
    {"symbol": "NVDA", "weight": 0.3},
    {"symbol": "AMD", "weight": 0.3},
]
PRICES = {"MSFT": 400.0, "NVDA": 100.0, "AMD": 150.0}


def _cell(marker: str) -> str:
    cells = json.loads(NOTEBOOK.read_text(encoding="utf-8"))["cells"]
    matches = [
        "".join(c["source"])
        for c in cells
        if c["cell_type"] == "code" and marker in "".join(c["source"])
    ]
    assert len(matches) == 1, marker
    return matches[0]


def _stubs() -> dict:
    return {
        "nb_panel": lambda *a, **k: None,
        "nb_pill": lambda *a, **k: "",
        "nb_table": lambda *a, **k: "",
    }


def test_candidate_trades_follow_the_conviction_rule() -> None:
    """Top names: positive composite buys 5, negative closes 20."""
    trades = candidate_trades(CONVICTION, top_n=3)
    assert [(t["symbol"], t["action"], t["delta_shares"]) for t in trades] == [
        ("MSFT", "buy", 5),
        ("NVDA", "buy", 5),
        ("AMD", "close", -20),
    ]
    assert trades[2]["rationale"] == "smart_money composite -0.58 (4 signals)"


def test_candidate_trades_accept_objects_and_labels() -> None:
    """Model objects work like dicts, and a fixture label is carried."""
    item = SimpleNamespace(symbol="MSFT", composite=0.0, signal_count=2)
    [trade] = candidate_trades([item], label="FIXTURE", buy_shares=7, close_shares=3)
    assert (trade["action"], trade["delta_shares"]) == ("close", -3)
    assert trade["rationale"].endswith("— FIXTURE")


def test_no_conviction_means_no_trades() -> None:
    """Nothing is invented when the rollup is empty."""
    assert not candidate_trades([])


def test_whatif_diff_by_hand() -> None:
    """$100k: MSFT 100 sh, NVDA 300 sh, AMD 200 sh; then +5 NVDA, -20 AMD."""
    diff = whatif_weight_diff(
        BASKET,
        PRICES,
        [{"symbol": "NVDA", "delta_shares": 5}, {"symbol": "AMD", "delta_shares": -20}],
        account_size=100_000,
    )
    # After: MSFT 40000, NVDA 30500, AMD 27000 -> total 97500
    assert diff.weights_before == pytest.approx({"MSFT": 0.4, "NVDA": 0.3, "AMD": 0.3})
    assert diff.weights_after == pytest.approx(
        {"MSFT": 40000 / 97500, "NVDA": 30500 / 97500, "AMD": 27000 / 97500}
    )
    assert diff.hhi_before == pytest.approx(0.34)
    after = [40000 / 97500, 30500 / 97500, 27000 / 97500]
    assert diff.hhi_after == pytest.approx(sum(w * w for w in after))
    assert diff.effective_n_before == pytest.approx(1 / 0.34)
    assert diff.verdict == "concentrated"


def test_share_trades_depend_on_the_account_size() -> None:
    """$50k: MSFT 50 sh; selling 30 leaves 20 sh = $8000 of $38000."""
    diff = whatif_weight_diff(
        BASKET, PRICES, [{"symbol": "MSFT", "delta_shares": -30}], account_size=50_000
    )
    assert diff.weights_after["MSFT"] == pytest.approx(8000 / 38000)


def test_a_new_name_needs_a_price() -> None:
    """A trade in a symbol with no price is an error, not a $100 guess."""
    with pytest.raises(ValueError, match="TSLA"):
        whatif_weight_diff(BASKET, PRICES, [{"symbol": "TSLA", "delta_shares": 1}])


def test_a_trade_cannot_go_short() -> None:
    """Selling more shares than are held is rejected."""
    with pytest.raises(ValueError, match="short"):
        whatif_weight_diff(
            BASKET,
            PRICES,
            [{"symbol": "AMD", "delta_shares": -500}],
            account_size=100_000,
        )


@pytest.mark.parametrize(
    ("delta", "verdict"),
    [
        (-30, "diversified"),
        (0, "unchanged"),
        # +1 MSFT moves HHI by about +0.0005, inside the 0.001 tolerance.
        (1, "unchanged"),
    ],
)
def test_verdict_thresholds(delta, verdict) -> None:
    """HHI moves of more than 0.001 either way decide the verdict."""
    diff = whatif_weight_diff(
        BASKET,
        PRICES,
        [{"symbol": "MSFT", "delta_shares": delta}],
        account_size=100_000,
    )
    assert diff.verdict == verdict


# --- notebook parity ------------------------------------------------------

pytest_notebook = pytest.mark.skipif(
    not NOTEBOOK.is_file(), reason="portfolio notebooks are not in this checkout"
)


@pytest_notebook
def test_candidate_trades_match_notebook_section_2() -> None:
    """The §2 trades come out identical."""
    namespace = {"sm_artifact": {"top_conviction": CONVICTION}, **_stubs()}
    exec(_cell("[Phase B / NB05 §2]"), namespace)  # noqa: S102
    assert candidate_trades(CONVICTION, top_n=3) == namespace["trades"]


@pytest_notebook
def test_whatif_diff_matches_notebook_sections_3_and_4(monkeypatch) -> None:
    """Weights, HHI, effective-N and the §4 verdict match the notebook."""
    trades = candidate_trades(CONVICTION, top_n=3)

    def _quote(symbol, provider):
        return SimpleNamespace(
            to_df=lambda: pd.DataFrame({"last_price": [PRICES[symbol]]})
        )

    fake = ModuleType("openbb")
    fake.obb = SimpleNamespace(
        equity=SimpleNamespace(price=SimpleNamespace(quote=_quote))
    )
    monkeypatch.setitem(sys.modules, "openbb", fake)
    namespace = {"basket": BASKET, "trades": trades, **_stubs()}
    section_3 = _cell("[Phase B / NB05 §3]").split("# ---- render")[0]
    exec(section_3, namespace)  # noqa: S102
    exec(_cell("[Phase B / NB05 §4]"), namespace)  # noqa: S102
    diff = whatif_weight_diff(BASKET, PRICES, trades, account_size=100_000)
    assert diff.weights_before == pytest.approx(namespace["w_current"])
    assert diff.weights_after == pytest.approx(namespace["w_new"])
    assert diff.hhi_before == pytest.approx(namespace["h_c"])
    assert diff.hhi_after == pytest.approx(namespace["h_n"])
    assert diff.effective_n_after == pytest.approx(namespace["neff_n"])
    tone = {"concentrated": "bad", "diversified": "good", "unchanged": "neutral"}
    assert tone[diff.verdict] == namespace["_verdict_tone"]
