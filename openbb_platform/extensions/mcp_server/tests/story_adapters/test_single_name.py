"""Seven-phase single-name analysis story tool (#2314, N05b).

The pipeline is the real ``Analysis/stock_analysis`` module. Unit tests stub
only its ``run_full_analysis`` entry point, and the stub returns instances of
the module's own phase dataclasses, so a renamed or added phase field shows
up here as a contract failure rather than passing silently.
"""

# pylint: disable=redefined-outer-name,unused-argument,consider-using-with

import dataclasses
import hashlib
import json
import math
import os
import sys
import typing
from pathlib import Path
from types import ModuleType

import pandas as pd
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from openbb_mcp_server.story_adapters import single_name
from openbb_mcp_server.story_adapters.single_name import compose_single_name_app

REPO_ROOT = Path(__file__).resolve().parents[5]
ANALYSIS_DIR = REPO_ROOT / "Analysis"
ROUTE = "/api/v1/story/analytics/single_name"
PHASES = [f"p{i}" for i in range(1, 8)]

pytestmark = pytest.mark.skipif(
    not (ANALYSIS_DIR / "stock_analysis.py").is_file(),
    reason="Analysis/ is not in this checkout",
)


def _frame(rows: int) -> pd.DataFrame:
    index = pd.date_range("2026-01-01", periods=rows, freq="D")
    return pd.DataFrame(
        {
            "date": index,
            "close": [float(i) for i in range(rows)],
            "gap": [math.nan] * rows,
        }
    )


def _value(annotation, name):
    """Synthesize a realistic value for one dataclass field annotation."""
    text = str(annotation)
    if "DataFrame" in text:
        return _frame(300 if name == "price_df" else 3)
    if "None" in text:
        return None
    if text in {"float", "<class 'float'>"}:
        return math.nan if name == "free_float_pct" else 1.25
    if text in {"int", "<class 'int'>"}:
        return 3
    if text in {"bool", "<class 'bool'>"}:
        return name != "gate_passed" or True
    if text in {"str", "<class 'str'>"}:
        return f"{name}-text"
    if text.startswith("dict"):
        return {"a": 1.0, "when": pd.Timestamp("2026-02-01"), "bad": math.inf}
    if text.startswith("list"):
        return ["PEER1", "PEER2"]
    return None


def _result(module, stop_after=None, regime=None):
    results = {}
    for index, key in enumerate(PHASES, start=1):
        cls = getattr(module, f"Phase{index}Result")
        hints = typing.get_type_hints(cls, vars(module))
        values = {
            f.name: _value(hints[f.name], f.name) for f in dataclasses.fields(cls)
        }
        if "regime" in values:
            values["regime"] = regime
        results[key] = cls(**values)
    if stop_after:
        # Like the engine: drop later phases, record where it stopped and put
        # a synthesized "Gate Failed" phase 7 in place of a real decision.
        stopped = PHASES.index(stop_after) + 1
        for key in PHASES[stopped:-1]:
            results.pop(key)
        results[stop_after].gate_passed = False
        results["p7"].action_label = "Gate Failed"
        results["stopped_at"] = stop_after
    return results


@pytest.fixture
def pipeline(monkeypatch):
    """Load the real pipeline module and record each run_full_analysis call."""
    monkeypatch.setenv(single_name.ANALYSIS_DIR_ENV, str(ANALYSIS_DIR))
    module = single_name.load_pipeline()
    calls = []

    def _run(cfg, *, regime=None):
        calls.append((cfg, regime))
        return _result(module, regime=regime)

    monkeypatch.setattr(module, "run_full_analysis", _run)
    return module, calls


@pytest.fixture
def client(pipeline):
    """Return a test client over the composed single-name route."""
    return TestClient(compose_single_name_app(FastAPI()))


def test_every_phase_and_field_is_returned(client, pipeline):
    """All seven phases come back with every field the engine defines."""
    module, _ = pipeline
    response = client.post(ROUTE, json={"symbol": "msft"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["phases"]) == PHASES
    for index, key in enumerate(PHASES, start=1):
        fields = {
            f.name for f in dataclasses.fields(getattr(module, f"Phase{index}Result"))
        }
        assert set(body["phases"][key]) == fields, key
    assert "composite_score" in body["phases"]["p7"]
    assert body["phases"]["p2"]["score"] == 1.25


def test_the_response_is_strict_json(client, pipeline):
    """NaN, infinity and timestamps never leak into the response."""
    body = client.post(ROUTE, json={"symbol": "MSFT"}).json()
    json.dumps(body, allow_nan=False)
    assert body["phases"]["p1"]["free_float_pct"] is None
    nested = body["phases"]["p3"]["signals"]
    assert nested == {"a": 1.0, "when": "2026-02-01T00:00:00", "bad": None}


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_non_finite_numbers_become_null(value):
    """The converter itself never emits NaN or infinity."""
    assert single_name._json_value(value) is None  # pylint: disable=protected-access
    assert single_name._json_value(  # pylint: disable=protected-access
        {"x": [value]}
    ) == {"x": [None]}


@pytest.mark.parametrize(
    ("rows", "expected"), [(None, single_name.DEFAULT_FRAME_ROWS), (0, 0), (3, 3)]
)
def test_frame_rows_are_chosen_by_the_caller(client, pipeline, rows, expected):
    """Frames default to a few rows; zero returns columns and counts only."""
    body = (
        {"symbol": "MSFT"}
        if rows is None
        else {"symbol": "MSFT", "max_frame_rows": rows}
    )
    frame = client.post(ROUTE, json=body).json()["phases"]["p3"]["price_df"]
    assert len(frame["rows"]) == expected
    assert frame["row_count"] == 300


def test_frame_rows_are_capped(client):
    """No caller can ask for more than MAX_FRAME_ROWS rows per frame."""
    response = client.post(
        ROUTE, json={"symbol": "MSFT", "max_frame_rows": single_name.MAX_FRAME_ROWS + 1}
    )
    assert response.status_code == 422


def test_frames_are_bounded_to_their_latest_rows(client, pipeline):
    """A long frame returns its latest rows plus its true size."""
    body = client.post(
        ROUTE, json={"symbol": "MSFT", "max_frame_rows": single_name.MAX_FRAME_ROWS}
    ).json()
    frame = body["phases"]["p3"]["price_df"]
    assert frame["row_count"] == 300
    assert frame["columns"] == ["date", "close", "gap"]
    assert len(frame["rows"]) == single_name.MAX_FRAME_ROWS
    assert frame["rows"][-1] == {
        "date": "2026-10-27T00:00:00",
        "close": 299.0,
        "gap": None,
    }


def test_configuration_reaches_the_engine(client, pipeline):
    """Symbol, benchmark, flags, gates and regime are passed through."""
    module, calls = pipeline
    response = client.post(
        ROUTE,
        json={
            "symbol": "aapl",
            "benchmark": "qqq",
            "feature_flags": {"use_regime_input": True, "use_two_stage_dcf": True},
            "enforce_gates": True,
            "regime": "crisis",
        },
    )
    assert response.status_code == 200, response.text
    cfg, regime = calls[-1]
    assert (cfg.symbol, cfg.benchmark, cfg.enforce_gates) == ("AAPL", "QQQ", True)
    assert cfg.feature_flags == module.AnalysisFeatureFlags(
        use_regime_input=True, use_two_stage_dcf=True
    )
    assert getattr(regime, "value", regime) == "CRISIS"
    assert response.json()["phases"]["p7"]["regime"] == "CRISIS"


@pytest.mark.parametrize(
    "body",
    [
        {"symbol": "MS FT"},
        {"symbol": ""},
        {"symbol": "MSFT", "feature_flags": {"use_everything": True}},
        {"symbol": "MSFT", "regime": "CRISIS"},
        {
            "symbol": "MSFT",
            "feature_flags": {"use_regime_input": True},
            "regime": "MOON",
        },
    ],
)
def test_bad_requests_are_rejected(client, body):
    """Unknown flags, bad symbols and an ineffective regime are 422s."""
    assert client.post(ROUTE, json=body).status_code == 422


def test_provenance_and_diagnostics(client, pipeline):
    """The response says what ran, on what code, and how each gate went."""
    body = client.post(ROUTE, json={"symbol": "MSFT"}).json()
    provenance = body["provenance"]
    assert provenance["provider"] == "fmp_cached"
    assert provenance["engine"] == "Analysis/stock_analysis.run_full_analysis"
    source = (ANALYSIS_DIR / "stock_analysis.py").read_bytes()
    assert provenance["engine_sha256"] == hashlib.sha256(source).hexdigest()
    assert provenance["symbol"] == "MSFT"
    assert set(provenance["feature_flags"]) == {
        f.name for f in dataclasses.fields(pipeline[0].AnalysisFeatureFlags)
    }
    gates = body["diagnostics"]["gates"]
    assert [g["phase"] for g in gates] == PHASES
    assert all(set(g) == {"phase", "gate_passed", "gate_notes"} for g in gates)
    assert body["diagnostics"]["stopped_at"] is None
    assert body["diagnostics"]["phases_not_run"] == []


def test_a_stopped_pipeline_says_where(client, pipeline, monkeypatch):
    """With enforce_gates, unrun phases are named, never invented."""
    module, _ = pipeline
    monkeypatch.setattr(
        module, "run_full_analysis", lambda cfg, *, regime=None: _result(module, "p2")
    )
    body = client.post(ROUTE, json={"symbol": "MSFT", "enforce_gates": True}).json()
    assert sorted(body["phases"]) == ["p1", "p2"]
    assert body["diagnostics"]["gates"][-1]["gate_passed"] is False
    assert body["diagnostics"]["stopped_at"] == "p2"
    assert body["diagnostics"]["phases_not_run"] == ["p3", "p4", "p5", "p6", "p7"]


def test_a_missing_pipeline_is_unavailable(tmp_path, monkeypatch):
    """Without Analysis/ the tool says so instead of failing obscurely."""
    monkeypatch.setenv(single_name.ANALYSIS_DIR_ENV, str(tmp_path))
    monkeypatch.delitem(sys.modules, "stock_analysis", raising=False)
    response = TestClient(compose_single_name_app(FastAPI())).post(
        ROUTE, json={"symbol": "MSFT"}
    )
    assert response.status_code == 503
    assert "Analysis" in response.json()["detail"]


def _fake_install(root: Path, *, git: bool) -> Path:
    """Lay out ``root`` like a checkout (or an install) of this server."""
    module = (
        root
        / "openbb_platform"
        / "extensions"
        / "mcp_server"
        / "openbb_mcp_server"
        / "story_adapters"
        / "single_name.py"
    )
    module.parent.mkdir(parents=True)
    module.write_text("", encoding="utf-8")
    (root / "Analysis").mkdir()
    (root / "Analysis" / "stock_analysis.py").write_text("", encoding="utf-8")
    if git:
        (root / ".git").mkdir()
    return module


def test_the_default_location_must_be_a_checkout(tmp_path, monkeypatch):
    """Outside a verified checkout there is no default pipeline location."""
    monkeypatch.delenv(single_name.ANALYSIS_DIR_ENV, raising=False)
    installed = _fake_install(tmp_path / "site", git=False)
    checkout = _fake_install(tmp_path / "repo", git=True)
    assert single_name.default_analysis_dir(installed) is None
    assert single_name.default_analysis_dir(checkout) == tmp_path / "repo" / "Analysis"


def test_a_foreign_stock_analysis_module_is_refused(tmp_path, monkeypatch):
    """A module of the same name loaded from elsewhere is never reused."""
    impostor = ModuleType("stock_analysis")
    impostor.__file__ = str(tmp_path / "stock_analysis.py")
    impostor.run_full_analysis = lambda cfg, *, regime=None: {}
    monkeypatch.setenv(single_name.ANALYSIS_DIR_ENV, str(ANALYSIS_DIR))
    monkeypatch.setitem(sys.modules, "stock_analysis", impostor)
    with pytest.raises(single_name.PipelineUnavailable, match="different"):
        single_name.load_pipeline()
    response = TestClient(compose_single_name_app(FastAPI())).post(
        ROUTE, json={"symbol": "MSFT"}
    )
    assert response.status_code == 503


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
@pytest.mark.parametrize("target", ["dir", "file"])
def test_a_writable_pipeline_location_is_refused(tmp_path, monkeypatch, target):
    """Code another user could have written is not executed."""
    root = tmp_path / "Analysis"
    root.mkdir()
    source = root / "stock_analysis.py"
    source.write_text("def run_full_analysis(cfg, *, regime=None):\n    return {}\n")
    (root if target == "dir" else source).chmod(0o777 if target == "dir" else 0o666)
    monkeypatch.setenv(single_name.ANALYSIS_DIR_ENV, str(root))
    monkeypatch.delitem(sys.modules, "stock_analysis", raising=False)
    with pytest.raises(single_name.PipelineUnavailable, match="writable"):
        single_name.load_pipeline()


def test_a_pipeline_failure_is_a_502(client, pipeline, monkeypatch):
    """A provider or engine failure is an error, never a partial result."""
    module, _ = pipeline

    def _boom(cfg, *, regime=None):
        raise RuntimeError("upstream said no")

    monkeypatch.setattr(module, "run_full_analysis", _boom)
    response = client.post(ROUTE, json={"symbol": "MSFT"})
    assert response.status_code == 502
    assert "RuntimeError" in response.json()["detail"]


def test_concurrent_runs_are_bounded(client, pipeline):
    """When every run slot is busy the call is refused, not queued forever."""
    held = [
        single_name.RUN_SLOTS.acquire(blocking=False)
        for _ in range(single_name.MAX_CONCURRENT_RUNS)
    ]
    try:
        assert all(held)
        response = client.post(ROUTE, json={"symbol": "MSFT"})
        assert response.status_code == 429
    finally:
        for _ in held:
            single_name.RUN_SLOTS.release()
    assert client.post(ROUTE, json={"symbol": "MSFT"}).status_code == 200


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


@pytest.mark.asyncio
@pytest.mark.parametrize("profile", ["portfolio-read", "portfolio-ops"])
async def test_portfolio_profiles_expose_the_tool(profile, pipeline):
    """Both Portfolio profiles admit the single-name tool."""
    names = {tool.name for tool in await (await _server(profile)).list_tools()}
    assert "story_single_name_analysis" in names


@pytest.mark.asyncio
async def test_standard_profile_has_no_single_name_tool(pipeline):
    """The compatibility default never composes it."""
    names = {
        tool.name for tool in await (await _server("platform-standard")).list_tools()
    }
    assert "story_single_name_analysis" not in names


@pytest.mark.asyncio
async def test_single_name_over_mcp(pipeline):
    """A real MCP tool call returns all seven phases."""
    mcp = await _server("portfolio-read")
    result = await mcp.call_tool("story_single_name_analysis", {"symbol": "MSFT"})
    assert sorted(result.structured_content["phases"]) == PHASES


def _has_fmp_cached_key() -> bool:
    """Return whether a fmp_cached key is configured where the Platform looks."""
    if os.getenv("OPENBB_FMP_CACHED_API_KEY") or os.getenv("FMP_API_KEY"):
        return True
    settings = Path.home() / ".openbb_platform" / "user_settings.json"
    try:
        credentials = json.loads(settings.read_text(encoding="utf-8")).get(
            "credentials", {}
        )
    except (OSError, ValueError):
        return False
    return bool(credentials.get("fmp_cached_api_key"))


@pytest.mark.integration
@pytest.mark.skipif(
    not _has_fmp_cached_key(),
    reason="live run needs a fmp_cached_api_key (environment or user_settings.json)",
)
def test_live_single_name_run(monkeypatch):
    """One honest live run through fmp_cached (needs keys and network)."""
    monkeypatch.setenv(single_name.ANALYSIS_DIR_ENV, str(ANALYSIS_DIR))
    client = TestClient(compose_single_name_app(FastAPI()))
    response = client.post(ROUTE, json={"symbol": "MSFT"})
    assert response.status_code == 200, response.text
    body = response.json()
    assert sorted(body["phases"]) == PHASES
    assert body["phases"]["p1"]["market_cap"] > 0
    json.dumps(body, allow_nan=False)
