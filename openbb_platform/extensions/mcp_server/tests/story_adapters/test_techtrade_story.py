"""TechTrade story tools (#2316, N05d).

Provider lookups are replaced at the adapter's seams with synthetic data;
the TechTrade engine underneath is real, and expected values are worked out
by hand.
"""

# pylint: disable=redefined-outer-name,unused-argument

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import techtrade_story
from openbb_mcp_server.story_adapters.techtrade_story import compose_techtrade_story_app

PREFIX = "/api/v1/story/techtrade"


class FakeProviders:
    """Synthetic provider responses recorded at the adapter seams."""

    def __init__(self):
        self.forward_calls = []

    def closes(self, symbol, lookback_days):
        """Return a calm uptrend, or fail for BOOM."""
        if symbol == "BOOM":
            raise RuntimeError("upstream timeout")
        return [100.0 * 1.002**i * (1 + 0.001 * (-1) ** i) for i in range(260)]

    def forward_bars(self, symbol, as_of, days_ahead):
        """Return two forward bars; NONE has none and BOOM fails."""
        self.forward_calls.append(symbol)
        if symbol == "BOOM":
            raise RuntimeError("upstream timeout")
        if symbol == "NONE":
            return pd.DataFrame()
        index = pd.to_datetime(["2026-10-01", "2026-10-02"])
        return pd.DataFrame(
            [[101, 104, 99, 103], [103, 111, 102, 110]],
            index=index,
            columns=["open", "high", "low", "close"],
        )

    def institutional(self, symbol):
        """Return a synthetic 13F summary; UNKNOWN is not indexed."""
        if symbol == "UNKNOWN":
            return None
        return {
            "period": "2026-Q2",
            "holder_count": 3,
            "total_shares": 600,
            "total_value_usd": 60_000,
            "shares_outstanding": 1_000,
            "pct_institutional": 0.6,
            "shares_outstanding_source": "SEC EDGAR",
            "top_holders": [
                {"filer_name": "Fund A", "shares": 300, "value_usd": 30_000}
            ],
        }


@pytest.fixture
def providers(monkeypatch):
    """Replace the three provider seams with synthetic data."""
    fake = FakeProviders()
    monkeypatch.setattr(techtrade_story, "_daily_closes", fake.closes)
    monkeypatch.setattr(techtrade_story, "_forward_bars", fake.forward_bars)
    monkeypatch.setattr(techtrade_story, "_institutional", fake.institutional)
    return fake


@pytest.fixture
def client(providers):
    """Return a test client over the composed TechTrade story routes."""
    return TestClient(compose_techtrade_story_app(FastAPI()))


def test_market_weather_combines_with_p7(client):
    """A calm uptrend is green; with a strong phase-7 score it is a trade."""
    response = client.post(
        f"{PREFIX}/market_weather", json={"symbol": "SPY", "p7_composite_score": 3.8}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["verdict"] == "green"
    assert body["combined"] == "trade"
    assert {c["tone"] for c in body["components"].values()} == {"green"}


def test_market_weather_provider_failure_is_a_502(client):
    """An upstream failure is an error, never a made-up reading."""
    response = client.post(f"{PREFIX}/market_weather", json={"symbol": "BOOM"})
    assert response.status_code == 502
    assert "unavailable from the provider" in response.json()["detail"]


def _plan(symbol, segment, score, conviction="High", rr=2.5):
    return {
        "symbol": symbol,
        "segment": segment,
        "score": score,
        "action": "BUY",
        "conviction": conviction,
        "risk_reward": rr,
        "position_size": 100,
        "entry_price": 100.0,
        "stop_price": 95.0,
        "target_price": 112.5,
        "time_stop_bars": 10,
        "as_of": "2026-10-23",
        "votes": [{"family": "trend", "name": "ema", "vote": 1.0, "weight": 0.5}],
    }


def test_actionable_plans(client):
    """Filters, hold-by dates, audit and risk scaling come back together."""
    plans = [
        _plan("AAA", "Tech", 0.9),
        _plan("BBB", "Tech", 0.8),
        _plan("CCC", "Tech", 0.7),
        _plan("DDD", "Energy", 0.6, conviction="Low"),
    ]
    response = client.post(f"{PREFIX}/actionable_plans", json={"plans": plans})
    assert response.status_code == 200, response.text
    body = response.json()
    assert [p["symbol"] for p in body["actionable"]] == ["AAA", "BBB"]
    assert body["actionable"][0]["hold_by"] == "2026-11-06"
    assert body["audit"]["votes"][0]["contribution"] == pytest.approx(0.5)
    assert body["risk_scaling"][0] == {"risk": 0.005, "quantity": 50.0}


def test_round_trip_pnl(client):
    """Buy 10 at 100 and sell at 110 with 3 of costs nets 97."""
    fills = [
        {"side": "buy", "price": 100, "quantity": 10, "slippage": 0.5, "commission": 1},
        {
            "side": "sell",
            "price": 110,
            "quantity": 10,
            "slippage": 0.5,
            "commission": 1,
        },
    ]
    response = client.post(f"{PREFIX}/round_trip_pnl", json={"fills": fills})
    assert response.status_code == 200, response.text
    assert response.json()["net"] == pytest.approx(97.0)


def test_replay_recommendations(client, providers):
    """Each recommendation replays against forward bars; the summary follows."""
    recs = [
        {
            "symbol": "AAA",
            "action": "BUY",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 110,
            "position_size": 10,
            "conviction": "High",
            "risk_reward": 2.0,
        },
        {
            "symbol": "NONE",
            "action": "BUY",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 110,
            "position_size": 10,
            "conviction": "Low",
            "risk_reward": 2.0,
        },
    ]
    response = client.post(
        f"{PREFIX}/replay", json={"recommendations": recs, "as_of": "2026-09-30"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [o["status"] for o in body["outcomes"]] == ["target", "no-forward-bars"]
    assert body["outcomes"][0]["realized"] == pytest.approx(90.0)
    assert body["summary"]["win_rate"] == 1.0
    assert body["summary"]["failed"] == 1


def test_a_failed_fetch_is_reported_per_recommendation(client):
    """One unreachable symbol is marked fetch-failed; the rest still replay."""
    recs = [
        {
            "symbol": s,
            "action": "BUY",
            "entry_price": 100,
            "stop_price": 95,
            "target_price": 110,
            "position_size": 10,
        }
        for s in ("BOOM", "AAA")
    ]
    response = client.post(
        f"{PREFIX}/replay", json={"recommendations": recs, "as_of": "2026-09-30"}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert [o["status"] for o in body["outcomes"]] == ["fetch-failed", "target"]
    assert body["summary"]["failed"] == 1


def test_replay_fan_out_is_bounded(client):
    """At most MAX_REPLAYS recommendations per call."""
    rec = {
        "symbol": "AAA",
        "action": "BUY",
        "entry_price": 100,
        "stop_price": 95,
        "target_price": 110,
        "position_size": 10,
    }
    response = client.post(
        f"{PREFIX}/replay",
        json={"recommendations": [rec] * 26, "as_of": "2026-09-30"},
    )
    assert techtrade_story.MAX_REPLAYS == 25
    assert response.status_code == 422


def test_institutional_summary(client):
    """The local 13F index summary comes back with its provenance."""
    response = client.post(f"{PREFIX}/institutional", json={"symbol": "msft"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["symbol"] == "MSFT"
    assert body["pct_institutional"] == pytest.approx(0.6)


def test_unindexed_symbol_is_a_404(client):
    """A symbol the 13F index does not map is an explicit not-found."""
    response = client.post(f"{PREFIX}/institutional", json={"symbol": "UNKNOWN"})
    assert response.status_code == 404


def test_indicator_config_and_candidate_diff(client, monkeypatch):
    """Defaults, the tuned summary and a candidate's changed knobs."""
    monkeypatch.setattr(
        techtrade_story,
        "read_tuned",
        lambda: {
            "segments": {"Energy": {"meta": {"verdict": "robust", "tuned_at": "t"}}}
        },
    )
    knob = next(iter(techtrade_story.default_config()))
    response = client.post(
        f"{PREFIX}/indicator_config", json={"candidate": {knob: 999}}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["tuned_segments"] == [
        {"segment": "Energy", "verdict": "robust", "tuned_at": "t"}
    ]
    changed = [row for row in body["diff"] if row["changed"]]
    assert [row["knob"] for row in changed] == [knob]
    assert "symbol" in body["panel_parameters"]


def test_indicator_config_lists_the_tunable_knobs(client):
    """TechTrade chapter 5's knob table: the period knobs tuning searches."""
    from openbb_techtrade.tuning.tuneta_adapter import (  # pylint: disable=import-outside-toplevel
        KNOB_TABLE,
    )

    body = client.post(f"{PREFIX}/indicator_config", json={}).json()
    assert body["tunable_knobs"] == [
        {"field": field, "indicator": indicator, "low": low, "high": high}
        for field, indicator, (low, high) in KNOB_TABLE
    ]
    assert len(body["tunable_knobs"]) == 8
    assert {k["field"] for k in body["tunable_knobs"]} <= set(
        techtrade_story.default_config()
    )


def test_unknown_candidate_knob_is_rejected(client):
    """A candidate may only set knobs the config defines."""
    response = client.post(
        f"{PREFIX}/indicator_config", json={"candidate": {"not_a_knob": 1}}
    )
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("market_weather", '{"symbol": "SPY", "p7_composite_score": NaN}'),
        (
            "round_trip_pnl",
            '{"fills": [{"side": "buy", "price": Infinity, "quantity": 1}]}',
        ),
    ],
)
def test_non_finite_numbers_are_a_clean_422(client, path, body):
    """NaN and infinity are rejected with a JSON-encodable error."""
    response = client.post(
        f"{PREFIX}/{path}", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    assert "finite" in response.text


async def _server(profile):
    # pylint: disable=import-outside-toplevel
    from openbb_mcp_server.app.app import create_mcp_server
    from openbb_mcp_server.models.settings import MCPSettings

    settings = MCPSettings(
        api_prefix="/api/v1",
        capability_profile=profile,
        default_tool_categories=["all"],
        default_skills_dir=None,
    )
    auth = ("synthetic-user", "x" * 32) if profile != "platform-standard" else None
    return create_mcp_server(settings, FastAPI(), auth=auth)


TOOLS = {
    "story_market_weather",
    "story_actionable_plans",
    "story_round_trip_pnl",
    "story_replay_recommendations",
    "story_institutional_summary",
    "story_indicator_config",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
async def test_portfolio_profiles_expose_the_tools(profile, providers):
    """Both Portfolio profiles admit the six tools."""
    names = {tool.name for tool in await (await _server(profile)).list_tools()}
    assert names >= TOOLS


@pytest.mark.asyncio
async def test_standard_profile_has_none_of_them(providers):
    """The compatibility default never composes them."""
    names = {
        tool.name for tool in await (await _server("platform-standard")).list_tools()
    }
    assert not names & TOOLS


@pytest.mark.asyncio
async def test_round_trip_over_mcp(providers):
    """A real MCP tool call returns the P&L."""
    mcp = await _server("portfolio-read")
    fills = [
        {"side": "sell_short", "price": 100, "quantity": 10},
        {"side": "buy_to_cover", "price": 90, "quantity": 10},
    ]
    result = await mcp.call_tool("story_round_trip_pnl", {"fills": fills})
    assert result.structured_content["gross"] == pytest.approx(100.0)
