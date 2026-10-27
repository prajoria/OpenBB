"""Basket look-through and concentration story tools (#2313, N05a).

Provider lookups are replaced at the adapter's seams with synthetic data;
the engine underneath is the real one, and every expected number is worked
out by hand from the synthetic inputs.
"""

# pylint: disable=redefined-outer-name,unused-argument

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import analytics
from openbb_mcp_server.story_adapters.analytics import compose_story_analytics_app

PREFIX = "/api/v1/story/analytics"
HOLDINGS = {
    "EQX": [
        {"name": "Alpha Corp", "weight": 0.6, "asset_category": "EC"},
        {"name": "Beta Inc", "weight": 0.3, "asset_category": "EC"},
        {"name": "Cash Sweep", "weight": 0.1, "asset_category": "STIV"},
    ],
    "BDX": [{"name": "Treasury 1", "weight": 1.0, "asset_category": "DBT"}],
    "EQZ": [{"name": "Alpha Corp", "weight": 1.0, "asset_category": "EC"}],
}
TICKERS = {"Alpha Corp": "ALP", "Beta": "BET"}  # "Beta Inc" resolves stripped
SECTORS = {"ALP": "Technology", "BET": "Health Care", "SNGL": "Energy"}
CLASSES = {
    "equity_etfs": ["EQX", "MISS"],
    "bond_etfs": ["BDX"],
    "commodity_trusts": ["GLDX"],
}
BASKET = [
    {"symbol": "EQX", "weight": 0.5},
    {"symbol": "BDX", "weight": 0.2},
    {"symbol": "GLDX", "weight": 0.1},
    {"symbol": "MISS", "weight": 0.1},
    {"symbol": "SNGL", "weight": 0.1},
]


class FakeProviders:
    """Synthetic provider responses recorded at the adapter seams."""

    def __init__(self):
        self.searches: list[str] = []

    def nport_rows(self, symbol):
        """Return a fund's synthetic holdings, or the provider sentinel."""
        if symbol == "BOOM":
            raise RuntimeError("upstream timeout")
        if symbol not in HOLDINGS:
            raise analytics.NportUnavailable(f"{symbol}: not an N-PORT filer")
        return HOLDINGS[symbol]

    def search_ticker(self, query):
        """Record the query and return its synthetic ticker."""
        self.searches.append(query)
        return TICKERS.get(query)

    def profile_sector(self, symbol):
        """Return a synthetic sector; one symbol simulates an outage."""
        if symbol == "FAIL":
            raise RuntimeError("profile outage")
        return SECTORS.get(symbol)


@pytest.fixture
def providers(monkeypatch):
    """Replace the three provider seams with synthetic data."""
    fake = FakeProviders()
    monkeypatch.setattr(analytics, "_nport_rows", fake.nport_rows)
    monkeypatch.setattr(analytics, "_search_ticker", fake.search_ticker)
    monkeypatch.setattr(analytics, "_profile_sector", fake.profile_sector)
    return fake


@pytest.fixture
def client(providers):
    """Return a test client over the composed story analytics routes."""
    return TestClient(compose_story_analytics_app(FastAPI()))


def test_effective_positions_flatten_the_basket(client):
    """Funds flatten by class; positions come back heaviest first."""
    response = client.post(
        f"{PREFIX}/basket/effective_positions",
        json={"basket": BASKET, "top_n_per_etf": 2, **CLASSES},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    positions = {p["key"]: p["weight"] for p in body["positions"]}
    assert positions == pytest.approx(
        {
            "Alpha Corp": 0.30,
            "Beta Inc": 0.15,
            "TAIL_EQX": 0.05,
            "BOND_BDX": 0.20,
            "GLDX": 0.10,
            "MISS": 0.10,
            "SNGL": 0.10,
        }
    )
    weights = [p["weight"] for p in body["positions"]]
    assert weights == sorted(weights, reverse=True)
    assert body["coverage"] == pytest.approx(1.0)
    assert body["non_nport"] == ["MISS"]
    assert {o["symbol"] for o in body["opaque"]} == {"GLDX", "MISS"}


def test_a_provider_failure_is_an_error_not_a_flattened_basket(client):
    """An upstream failure is a 502, never a partial look-through."""
    response = client.post(
        f"{PREFIX}/basket/effective_positions",
        json={"basket": [{"symbol": "BOOM", "weight": 1.0}], "equity_etfs": ["BOOM"]},
    )
    assert response.status_code == 502
    assert "BOOM" in response.json()["detail"]


def test_sector_view_rolls_up_through_holdings(client, providers):
    """Issuers resolve to sectors, retrying a name without its suffix."""
    response = client.post(
        f"{PREFIX}/basket/sector_view",
        json={"basket": BASKET, "top_n_resolve": 30, **CLASSES},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    sectors = {s["sector"]: s["weight"] for s in body["sectors"]}
    assert sectors == pytest.approx(
        {
            "Technology": 0.30,  # 0.5 * 0.6 Alpha Corp
            "Health Care": 0.15,  # 0.5 * 0.3 Beta Inc, via its stripped name
            "Short-Term / Cash": 0.05,
            "Fixed Income": 0.20,
            "Commodity": 0.10,
            "MISS": 0.10,
            "Energy": 0.10,
        }
    )
    assert body["unknown_count"] == 0
    assert body["lookup_errors"] == 0


def test_an_issuer_held_by_two_funds_is_looked_up_once(client, providers):
    """Lookups are cached for the whole request."""
    response = client.post(
        f"{PREFIX}/basket/sector_view",
        json={
            "basket": [
                {"symbol": "EQX", "weight": 0.5},
                {"symbol": "EQZ", "weight": 0.5},
            ],
            "equity_etfs": ["EQX", "EQZ"],
        },
    )
    assert response.status_code == 200, response.text
    sectors = {s["sector"]: s["weight"] for s in response.json()["sectors"]}
    assert sectors["Technology"] == pytest.approx(0.30 + 0.50)
    assert providers.searches.count("Alpha Corp") == 1


def test_sector_lookup_failures_are_counted_not_hidden(client):
    """A failed sector lookup is Unknown and counted."""
    response = client.post(
        f"{PREFIX}/basket/sector_view",
        json={"basket": [{"symbol": "FAIL", "weight": 1.0}]},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["sectors"] == [{"sector": "Unknown", "weight": 1.0}]
    assert body["lookup_errors"] == 1


def test_concentration_by_hand(client):
    """HHI, effective-N, top-1 and the kill shot match hand arithmetic."""
    response = client.post(
        f"{PREFIX}/concentration",
        json={"weights": {"A": 0.5, "B": 0.3, "C": 0.2}, "kill_shot_drop": 0.5},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hhi"] == pytest.approx(0.38)  # .25 + .09 + .04
    assert body["effective_n"] == pytest.approx(1 / 0.38)
    assert body["top1"] == pytest.approx(0.5)
    assert body["largest"] == "A"
    assert body["kill_shot"] == pytest.approx(0.25)


@pytest.mark.parametrize(
    "weights",
    [{"A": -0.1}, {}, {f"N{i}": 0.0001 for i in range(analytics.MAX_WEIGHTS + 1)}],
)
def test_concentration_rejects_bad_weight_maps(client, weights):
    """Negative, empty and oversized weight maps are rejected."""
    response = client.post(f"{PREFIX}/concentration", json={"weights": weights})
    assert response.status_code == 422


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("concentration", '{"weights": {"A": NaN}}'),
        ("concentration", '{"weights": {"A": 0.5}, "kill_shot_drop": Infinity}'),
        ("basket/effective_positions", '{"basket": [{"symbol": "A", "weight": NaN}]}'),
        ("construction", '{"effective": {"A": 1.0}, "top5_cap": NaN}'),
    ],
)
def test_non_finite_numbers_are_a_clean_422(client, path, body):
    """NaN and infinity are rejected with a JSON-encodable error."""
    response = client.post(
        f"{PREFIX}/{path}",
        content=body,
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 422
    assert "finite" in response.text


def test_basket_size_is_bounded(client):
    """A basket larger than the limit is rejected."""
    basket = [
        {"symbol": f"S{i}", "weight": 0.001} for i in range(analytics.MAX_BASKET + 1)
    ]
    response = client.post(
        f"{PREFIX}/basket/effective_positions", json={"basket": basket}
    )
    assert response.status_code == 422


def test_funds_per_request_are_bounded(client):
    """One call cannot fan out to more than MAX_FUNDS N-PORT fetches."""
    funds = [f"F{i}" for i in range(analytics.MAX_FUNDS + 1)]
    response = client.post(
        f"{PREFIX}/basket/effective_positions",
        json={
            "basket": [{"symbol": f, "weight": 0.001} for f in funds],
            "equity_etfs": funds,
        },
    )
    assert response.status_code == 422
    assert "funds" in response.text


def test_sector_lookups_per_request_are_bounded(client):
    """Funds times resolved issuers cannot exceed the lookup budget."""
    funds_allowed = analytics.MAX_SECTOR_LOOKUPS // 60
    funds = [f"F{i}" for i in range(funds_allowed + 1)]
    response = client.post(
        f"{PREFIX}/basket/sector_view",
        json={
            "basket": [{"symbol": f, "weight": 0.001} for f in funds],
            "equity_etfs": funds,
            "top_n_resolve": 60,
        },
    )
    assert response.status_code == 422
    assert "lookup" in response.text


def test_a_repeated_fund_is_fetched_once(client, monkeypatch):
    """Duplicate basket rows share one N-PORT fetch per request."""
    calls = []

    def _rows(symbol):
        calls.append(symbol)
        return HOLDINGS[symbol]

    monkeypatch.setattr(analytics, "_nport_rows", _rows)
    response = client.post(
        f"{PREFIX}/basket/effective_positions",
        json={
            "basket": [
                {"symbol": "EQX", "weight": 0.5},
                {"symbol": "EQX", "weight": 0.5},
            ],
            "equity_etfs": ["EQX"],
        },
    )
    assert response.status_code == 200, response.text
    assert calls == ["EQX"]
    positions = {p["key"]: p["weight"] for p in response.json()["positions"]}
    assert positions["Alpha Corp"] == pytest.approx(0.6)


def test_construction_refuses_thin_coverage(client):
    """Thin coverage is a refusal with no targets."""
    response = client.post(
        f"{PREFIX}/construction", json={"effective": {"A": 0.5, "B": 0.3}}
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["refused"] is True
    assert body["targets"] is None


def test_construction_enforces_caps(client):
    """Caps hold and no weight leaks out of the targets."""
    effective = {"A": 0.30, "B": 0.20}
    effective.update({f"S{i:02d}": 0.025 for i in range(20)})
    response = client.post(f"{PREFIX}/construction", json={"effective": effective})
    assert response.status_code == 200, response.text
    body = response.json()
    targets = {t["name"]: t for t in body["targets"]}
    assert max(t["target"] for t in targets.values()) <= 0.06 + 1e-9
    assert targets["A"]["status"] == "TRIM"
    assert sum(t["target"] for t in targets.values()) + body["residual"] == (
        pytest.approx(1.0)
    )


async def _server(profile, monkeypatch, providers):
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


ANALYTICS_TOOLS = {
    "story_basket_effective_positions",
    "story_basket_sector_view",
    "story_concentration",
    "story_construction_targets",
}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
async def test_portfolio_profiles_expose_the_analytics_tools(
    profile, monkeypatch, providers
):
    """Both Portfolio profiles admit the four tools."""
    mcp = await _server(profile, monkeypatch, providers)
    names = {tool.name for tool in await mcp.list_tools()}
    assert names >= ANALYTICS_TOOLS


@pytest.mark.asyncio
async def test_standard_profile_has_no_analytics_tools(monkeypatch, providers):
    """The compatibility default never composes them."""
    mcp = await _server("platform-standard", monkeypatch, providers)
    names = {tool.name for tool in await mcp.list_tools()}
    assert not names & ANALYTICS_TOOLS


@pytest.mark.asyncio
async def test_concentration_over_mcp(monkeypatch, providers):
    """A real MCP tool call returns the computed result."""
    mcp = await _server("portfolio-read", monkeypatch, providers)
    result = await mcp.call_tool(
        "story_concentration", {"weights": {"A": 0.5, "B": 0.5}}
    )
    assert result.structured_content["effective_n"] == pytest.approx(2.0)
