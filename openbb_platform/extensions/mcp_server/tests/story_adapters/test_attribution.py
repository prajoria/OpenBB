"""Brinson attribution, what-if diff and candidate-trade story tools (#2315, N05c).

The engines underneath are the real ones; expected numbers are worked out by
hand from the synthetic inputs.
"""

# pylint: disable=redefined-outer-name

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import attribution
from openbb_mcp_server.story_adapters.attribution import compose_attribution_app

PREFIX = "/api/v1/story/analytics"
GROUPS = [
    {"group": "Tech", "w_p": 0.6, "w_b": 0.5, "r_p": 0.10, "r_b": 0.08},
    {"group": "Bonds", "w_p": 0.4, "w_b": 0.5, "r_p": 0.02, "r_b": 0.03},
]
BASKET = [
    {"symbol": "MSFT", "weight": 0.4},
    {"symbol": "NVDA", "weight": 0.3},
    {"symbol": "AMD", "weight": 0.3},
]
PRICES = {"MSFT": 400.0, "NVDA": 100.0, "AMD": 150.0}


@pytest.fixture
def client():
    """Return a test client over the composed attribution routes."""
    return TestClient(compose_attribution_app(FastAPI()))


def test_brinson_by_hand(client):
    """R_p 0.068, R_b 0.055; allocation, selection, interaction add up."""
    response = client.post(f"{PREFIX}/brinson", json={"groups": GROUPS})
    assert response.status_code == 200, response.text
    body = response.json()
    # alloc = 0.1*(0.08-0.055) + (-0.1)*(0.03-0.055) = 0.0025 + 0.0025
    # selection = 0.5*0.02 + 0.5*(-0.01) = 0.005
    # interaction = 0.1*0.02 + (-0.1)*(-0.01) = 0.003
    assert body["active_return"] == pytest.approx(0.013)
    assert body["allocation"] == pytest.approx(0.005)
    assert body["selection"] == pytest.approx(0.005)
    assert body["interaction"] == pytest.approx(0.003)
    assert body["dominant_effect"] in {"allocation", "selection"}


def test_brinson_rejects_weights_that_do_not_sum_to_one(client):
    """The oracle's weight check surfaces as a 422, not a renormalization."""
    bad = [dict(GROUPS[0], w_p=0.7), GROUPS[1]]
    response = client.post(f"{PREFIX}/brinson", json={"groups": bad})
    assert response.status_code == 422
    assert "portfolio weights" in response.text


def test_whatif_diff_by_hand(client):
    """$100k basket; +5 NVDA and -20 AMD concentrate the book."""
    response = client.post(
        f"{PREFIX}/whatif_diff",
        json={
            "basket": BASKET,
            "prices": PRICES,
            "trades": [
                {"symbol": "NVDA", "delta_shares": 5},
                {"symbol": "AMD", "delta_shares": -20},
            ],
            "account_size": 100000,
        },
    )
    assert response.status_code == 200, response.text
    body = response.json()
    after = {w["symbol"]: w["weight"] for w in body["weights_after"]}
    assert after == pytest.approx(
        {"MSFT": 40000 / 97500, "NVDA": 30500 / 97500, "AMD": 27000 / 97500}
    )
    assert body["hhi_before"] == pytest.approx(0.34)
    assert body["verdict"] == "concentrated"


@pytest.mark.parametrize(
    ("change", "fragment"),
    [
        ({"prices": {"MSFT": 400.0, "NVDA": 100.0}}, "AMD"),
        ({"trades": [{"symbol": "AMD", "delta_shares": -5000}]}, "short"),
        ({"basket": BASKET + [{"symbol": "MSFT", "weight": 0.1}]}, "duplicate"),
    ],
)
def test_whatif_diff_refuses_to_guess(client, change, fragment):
    """Missing prices, shorts and duplicate rows are explicit 422s."""
    body = {"basket": BASKET, "prices": PRICES, "trades": [], **change}
    response = client.post(f"{PREFIX}/whatif_diff", json=body)
    assert response.status_code == 422
    assert fragment in response.text


def test_candidate_trades_follow_the_rule(client):
    """Top three: positive composite buys, negative closes."""
    ranking = [
        {"symbol": "MSFT", "composite": 0.72, "signal_count": 6},
        {"symbol": "AMD", "composite": -0.58, "signal_count": 4},
        {"symbol": "XOM", "composite": 0.1, "signal_count": 1},
        {"symbol": "IBM", "composite": 0.9, "signal_count": 9},
    ]
    response = client.post(
        f"{PREFIX}/candidate_trades",
        json={"top_conviction": ranking, "label": "FIXTURE"},
    )
    assert response.status_code == 200, response.text
    trades = response.json()["trades"]
    assert [(t["symbol"], t["action"], t["delta_shares"]) for t in trades] == [
        ("MSFT", "buy", 5),
        ("AMD", "close", -20),
        ("XOM", "buy", 5),
    ]
    assert all(t["rationale"].endswith("— FIXTURE") for t in trades)


def test_empty_conviction_gives_no_trades(client):
    """No ranking, no trades; the response says so rather than inventing some."""
    response = client.post(f"{PREFIX}/candidate_trades", json={"top_conviction": []})
    assert response.status_code == 200, response.text
    assert response.json() == {"trades": [], "note": "no conviction ranking; no trades"}


@pytest.mark.parametrize(
    ("path", "body"),
    [
        (
            "brinson",
            '{"groups": [{"group": "A", "w_p": NaN, "w_b": 1, "r_p": 0, "r_b": 0}]}',
        ),
        (
            "whatif_diff",
            '{"basket": [{"symbol": "A", "weight": 1}], "prices": {"A": Infinity}, "trades": []}',
        ),
        (
            "candidate_trades",
            '{"top_conviction": [{"symbol": "A", "composite": NaN, "signal_count": 1}]}',
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


def test_inputs_are_bounded(client):
    """Oversized group lists are rejected, however valid the weights."""
    assert attribution.MAX_ROWS == 200
    count = 201  # the documented bound, pinned literally
    groups = [
        {"group": f"G{i}", "w_p": 1 / count, "w_b": 1 / count, "r_p": 0.01, "r_b": 0.0}
        for i in range(count)
    ]
    response = client.post(f"{PREFIX}/brinson", json={"groups": groups})
    assert response.status_code == 422
    assert "at most" in response.text


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


TOOLS = {"story_brinson_attribution", "story_whatif_diff", "story_candidate_trades"}


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
async def test_portfolio_profiles_expose_the_tools(profile):
    """Both Portfolio profiles admit the three tools."""
    names = {tool.name for tool in await (await _server(profile)).list_tools()}
    assert names >= TOOLS


@pytest.mark.asyncio
async def test_standard_profile_has_none_of_them():
    """The compatibility default never composes them."""
    names = {
        tool.name for tool in await (await _server("platform-standard")).list_tools()
    }
    assert not names & TOOLS


@pytest.mark.asyncio
async def test_brinson_over_mcp():
    """A real MCP tool call returns the effects."""
    mcp = await _server("portfolio-read")
    result = await mcp.call_tool("story_brinson_attribution", {"groups": GROUPS})
    assert result.structured_content["active_return"] == pytest.approx(0.013)
