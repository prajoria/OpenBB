"""Dataset adapters for the canonical TechTrade EOD snapshot store."""

# ruff: noqa: D103

from __future__ import annotations

import warnings
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace

import openbb_techtrade.snapshot.adapters as adapters_module
import pytest
from openbb_techtrade.engine.scan import ScanSegmentWarning
from openbb_techtrade.models import Mover, MoverList
from openbb_techtrade.snapshot.adapters import (
    AuditSnapshotAdapter,
    EventKind,
    MarketEvent,
    MembershipSnapshot,
    MoversSnapshotAdapter,
    PublicEventRiskProvider,
    ScanSnapshotAdapter,
    SimulateSnapshotAdapter,
    TechTradeSnapshotAdapter,
    get_snapshot_adapters,
)
from openbb_techtrade.snapshot.datasets import (
    SURVIVORSHIP_UNCORRECTED,
    TECHTRADE_DATASETS,
)
from openbb_techtrade.snapshot.job import SnapshotJobState
from openbb_techtrade.snapshot.refresh import SnapshotRefreshOrchestrator
from openbb_techtrade.snapshot.registry import (
    DEFAULT_DATASET_REGISTRY,
    SnapshotStoreRouter,
)
from openbb_techtrade.snapshot.store import SnapshotStatus, SqliteSnapshotStore

SESSION = date(2026, 9, 11)
NOW = datetime(2026, 9, 11, 22, tzinfo=timezone.utc)
TECH = "Information Technology"
ENERGY = "Energy"


def _movers(segment: str, as_of: date, symbols: tuple[str, ...]) -> list[MoverList]:
    return [
        MoverList(
            segment=segment,
            as_of=as_of,
            movers=[
                Mover(
                    symbol=symbol,
                    pct_change=float(index + 1),
                    volume=Decimal("100"),
                    rank=index + 1,
                )
                for index, symbol in enumerate(symbols)
            ],
        )
    ]


def test_movers_computes_once_for_one_public_segment() -> None:
    calls: list[tuple[str, date, int]] = []

    def fetcher(*, segment: str, as_of: date, top_n: int, **_kwargs):
        calls.append((segment, as_of, top_n))
        return _movers(segment, as_of, ("NVDA", "AAPL"))

    adapter = MoversSnapshotAdapter(
        segments=[TECH],
        top_n=2,
        mover_fetcher=fetcher,
        event_fetcher=lambda _session, _symbols: [],
    )

    computed = adapter.compute("segment=information technology", SESSION)

    assert calls == [(TECH, SESSION, 2)]
    assert computed.payload["exchange_calendar"] == "XNYS"
    assert [row["symbol"] for row in computed.payload["rows"]] == ["NVDA", "AAPL"]
    assert computed.row_count == 2
    assert "credentials" not in str(computed.payload).lower()


def test_earnings_are_annotated_and_inactive_symbols_are_excluded() -> None:
    def fetcher(*, segment: str, as_of: date, **_kwargs):
        return _movers(segment, as_of, ("NVDA", "OLD", "HALT"))

    def events(_session: date, _symbols: list[str]) -> list[MarketEvent]:
        return [
            MarketEvent("NVDA", EventKind.EARNINGS),
            MarketEvent("OLD", EventKind.DELISTED),
            MarketEvent("HALT", EventKind.HALTED),
        ]

    computed = MoversSnapshotAdapter(
        segments=[TECH],
        mover_fetcher=fetcher,
        event_fetcher=events,
    ).compute("segment=information technology", SESSION)

    assert computed.payload["earnings_symbols"] == ["NVDA"]
    assert computed.payload["excluded_symbols"] == ["HALT", "OLD"]
    assert [row["symbol"] for row in computed.payload["rows"]] == ["NVDA"]
    assert computed.inputs["events"] == [
        {"kind": "earnings", "symbol": "NVDA"},
        {"kind": "delisted", "symbol": "OLD"},
        {"kind": "halted", "symbol": "HALT"},
    ]


def test_successful_movers_run_publishes_live_snapshot(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    adapter = MoversSnapshotAdapter(
        segments=[TECH],
        mover_fetcher=lambda *, segment, as_of, **_kwargs: _movers(
            segment, as_of, ("NVDA",)
        ),
        event_fetcher=lambda _session, _symbols: [],
    )
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY),
        DEFAULT_DATASET_REGISTRY,
        {adapter.name: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: "success",
    )

    job = orchestrator.run(adapter.name)

    live = store.get_live(adapter.name, "segment=information technology")
    assert job.state is SnapshotJobState.SUCCEEDED
    assert live is not None
    assert live.payload["rows"][0]["symbol"] == "NVDA"
    store.close()


def _seed_live(
    store: SqliteSnapshotStore, dataset: str, segment: str, job_run_id: str
) -> None:
    key = f"segment={segment}"
    store.stage(
        dataset,
        key,
        date(2026, 9, 10),
        job_run_id,
        {
            "rows": [{"symbol": "LAST", "pct_change": 1.0}],
            "segment": segment,
            "as_of_session": "2026-09-10",
            "exchange_calendar": "XNYS",
            "earnings_symbols": [],
            "excluded_symbols": [],
            "survivorship": "not-applicable",
        },
        status=SnapshotStatus.OK,
        row_count=1,
        engine_version="test",
        payload_schema_version="1",
    )
    definition = DEFAULT_DATASET_REGISTRY.require(dataset)
    assert store.validate(
        dataset,
        key,
        date(2026, 9, 10),
        job_run_id,
        lambda row: definition.validator(row, None),
    ).ok
    assert store.promote(dataset, key, date(2026, 9, 10), job_run_id)


def test_partial_movers_run_keeps_all_last_good_and_records_failed_key(
    tmp_path: Path,
) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    _seed_live(store, "techtrade.movers", TECH, "old-tech")
    _seed_live(store, "techtrade.movers", ENERGY, "old-energy")

    def fetcher(*, segment: str, as_of: date, **_kwargs):
        if segment == ENERGY:
            raise TimeoutError("private provider detail")
        return _movers(segment, as_of, ("NVDA",))

    adapter = MoversSnapshotAdapter(
        segments=[TECH, ENERGY],
        mover_fetcher=fetcher,
        event_fetcher=lambda _session, _symbols: [],
    )
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY),
        DEFAULT_DATASET_REGISTRY,
        {adapter.name: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: "partial",
    )

    job = orchestrator.run(adapter.name)

    assert job.state is SnapshotJobState.PARTIAL
    assert store.get_live(adapter.name, f"segment={TECH}").job_run_id == "old-tech"
    assert store.get_live(adapter.name, f"segment={ENERGY}").job_run_id == "old-energy"
    assert store.retry_entity_keys(job.job_run_id) == ["segment=energy"]
    assert "private provider detail" not in (store.get_job(job.job_run_id).error or "")
    store.close()


def test_validation_rejection_keeps_last_good(tmp_path: Path) -> None:
    store = SqliteSnapshotStore(tmp_path / "snapshot.db")
    _seed_live(store, "techtrade.movers", TECH, "old")

    adapter = MoversSnapshotAdapter(
        segments=[TECH],
        mover_fetcher=lambda **_kwargs: [
            {
                "segment": TECH,
                "as_of": SESSION.isoformat(),
                "movers": [{"symbol": "NVDA", "close": None}],
            }
        ],
        event_fetcher=lambda _session, _symbols: [],
    )
    orchestrator = SnapshotRefreshOrchestrator(
        SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY),
        DEFAULT_DATASET_REGISTRY,
        {adapter.name: adapter},
        clock=lambda: NOW,
        job_id_factory=lambda: "rejected",
    )

    job = orchestrator.run(adapter.name)

    assert job.state is SnapshotJobState.FAILED
    assert store.get_live(adapter.name, f"segment={TECH}").job_run_id == "old"
    assert store.retry_entity_keys(job.job_run_id) == ["segment=information technology"]
    store.close()


def test_pyproject_advertises_movers_snapshot_adapter() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert "openbb_snapshot_dataset" in text
    assert (
        "techtrade_movers = "
        '"openbb_techtrade.snapshot.adapters:MoversSnapshotAdapter"'
    ) in text
    for suffix, adapter in (
        ("scan", "ScanSnapshotAdapter"),
        ("signals", "SignalsSnapshotAdapter"),
        ("plan", "PlanSnapshotAdapter"),
        ("orders", "OrdersSnapshotAdapter"),
        ("simulate", "SimulateSnapshotAdapter"),
        ("validate", "ValidateSnapshotAdapter"),
        ("tune", "TuneSnapshotAdapter"),
        ("audit", "AuditSnapshotAdapter"),
    ):
        assert (
            f"techtrade_{suffix} = " f'"openbb_techtrade.snapshot.adapters:{adapter}"'
        ) in text


def test_adapter_registry_covers_every_consumer_dataset() -> None:
    assert tuple(get_snapshot_adapters()) == TECHTRADE_DATASETS


def test_sensitive_dataset_is_explicitly_survivorship_uncorrected() -> None:
    adapter = TechTradeSnapshotAdapter(
        "techtrade.validate",
        compute_fn=lambda _segment, _session: [{"symbol": "AAPL", "verdict": "robust"}],
        segments=[TECH],
    )

    computed = adapter.compute("segment=information technology", SESSION)

    assert computed.payload["survivorship"] == SURVIVORSHIP_UNCORRECTED
    assert computed.payload["universe_membership"] == []


def test_exact_as_of_membership_marks_sensitive_dataset_corrected() -> None:
    adapter = TechTradeSnapshotAdapter(
        "techtrade.audit",
        compute_fn=lambda _segment, _session: [
            {"symbol": "AAPL", "event": "replayed"},
            {"symbol": "OLD", "event": "replayed"},
        ],
        segments=[TECH],
        membership_fetcher=lambda _segment, _session: MembershipSnapshot(
            as_of_session=SESSION,
            exchange_calendar="XNYS",
            symbols=("AAPL",),
        ),
    )

    computed = adapter.compute("segment=information technology", SESSION)

    assert computed.payload["survivorship"] == "corrected"
    assert computed.payload["universe_membership"] == ["AAPL"]
    assert [row["symbol"] for row in computed.payload["rows"]] == ["AAPL"]


def test_wrong_session_membership_does_not_claim_correction() -> None:
    adapter = TechTradeSnapshotAdapter(
        "techtrade.tune",
        compute_fn=lambda _segment, _session: [{"symbol": "AAPL"}],
        segments=[TECH],
        membership_fetcher=lambda _segment, _session: MembershipSnapshot(
            as_of_session=date(2026, 9, 10),
            exchange_calendar="XNYS",
            symbols=("AAPL",),
        ),
    )

    computed = adapter.compute("segment=information technology", SESSION)

    assert computed.payload["survivorship"] == SURVIVORSHIP_UNCORRECTED


def test_public_event_provider_combines_earnings_delists_and_halts() -> None:
    provider = PublicEventRiskProvider(
        earnings_fetcher=lambda _session: [
            {"symbol": "NVDA", "date": SESSION.isoformat()},
            {"symbol": "OTHER", "date": SESSION.isoformat()},
        ],
        delisted_fetcher=lambda _session: [
            {"symbol": "OLD", "delisted_date": "2026-09-10"}
        ],
        halted_fetcher=lambda _session: [{"symbol": "HALT"}],
    )

    events = provider(SESSION, ["NVDA", "OLD", "HALT"])

    assert events == [
        MarketEvent("NVDA", EventKind.EARNINGS),
        MarketEvent("OLD", EventKind.DELISTED),
        MarketEvent("HALT", EventKind.HALTED),
    ]


def test_public_event_provider_ignores_future_delisting() -> None:
    provider = PublicEventRiskProvider(
        earnings_fetcher=lambda _session: [],
        delisted_fetcher=lambda _session: [
            {"symbol": "OLD", "delisted_date": "2026-09-12"}
        ],
        halted_fetcher=lambda _session: [],
    )

    assert provider(SESSION, ["OLD"]) == []


def test_public_event_provider_refreshes_sources_on_same_session() -> None:
    earnings: list[dict] = []
    provider = PublicEventRiskProvider(
        earnings_fetcher=lambda _session: list(earnings),
        delisted_fetcher=lambda _session: [],
        halted_fetcher=lambda _session: [],
    )
    assert provider(SESSION, ["NVDA"]) == []

    earnings.append({"symbol": "NVDA", "date": SESSION.isoformat()})

    assert provider(SESSION, ["NVDA"]) == [MarketEvent("NVDA", EventKind.EARNINGS)]


def _plan_stub(
    symbol: str = "NVDA",
    segment: str = TECH,
    *,
    simulated_fills: list | None = None,
    validation: object | None = None,
):
    recommendation = SimpleNamespace(
        action="BUY",
        conviction="High",
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        stop_distance_pct=0.05,
        target_distance_pct=0.10,
        risk_reward=2.0,
        atr=2.5,
        risk_per_share=Decimal("5"),
        risk_pct_of_notional=0.05,
        time_stop_bars=10,
        reasoning="test",
        top_factors=["trend"],
    )
    signal = SimpleNamespace(direction="long", score=0.9, rank_in_segment=1)
    return SimpleNamespace(
        symbol=symbol,
        segment=segment,
        as_of=SESSION,
        signal=signal,
        recommendation=recommendation,
        position_size=Decimal("10"),
        orders=[SimpleNamespace()],
        simulated_fills=simulated_fills or [],
        validation=validation,
    )


def test_scan_adapter_runs_canonical_scan_once_and_flattens_by_segment() -> None:
    calls: list[tuple[date, int, str]] = []

    def scan_fetcher(*, as_of: date, top_n: int, preset: str):
        calls.append((as_of, top_n, preset))
        return [_plan_stub("NVDA", TECH), _plan_stub("XOM", ENERGY)]

    adapter = ScanSnapshotAdapter(
        segments=[TECH, ENERGY],
        top_n=5,
        preset="breakout",
        scan_fetcher=scan_fetcher,
        event_fetcher=lambda _session, _symbols: [],
    )

    tech = adapter.compute("segment=information technology", SESSION)
    energy = adapter.compute("segment=energy", SESSION)

    assert calls == [(SESSION, 5, "breakout")]
    assert tech.payload["rows"][0]["symbol"] == "NVDA"
    assert tech.payload["rows"][0]["score"] == 0.9
    assert tech.payload["preset"] == "breakout"
    assert tech.payload["params"] == {"top_n": 5, "preset": "breakout"}
    assert energy.payload["rows"][0]["symbol"] == "XOM"


def test_scan_adapter_raises_for_segment_reported_failed() -> None:
    def scan_fetcher(**_kwargs):
        warnings.warn(ScanSegmentWarning(ENERGY, TimeoutError()), stacklevel=2)
        return [_plan_stub("NVDA", TECH)]

    adapter = ScanSnapshotAdapter(
        segments=[TECH, ENERGY],
        scan_fetcher=scan_fetcher,
        event_fetcher=lambda _session, _symbols: [],
    )

    adapter.compute("segment=information technology", SESSION)
    with pytest.raises(RuntimeError, match="scan_segment_failed"):
        adapter.compute("segment=energy", SESSION)


def test_simulation_adapter_materializes_actual_fill_pnl() -> None:
    fills = [
        SimpleNamespace(
            side="buy",
            quantity=Decimal("10"),
            price=Decimal("100"),
            commission=Decimal("0"),
            timestamp=datetime(2026, 9, 12, 14, tzinfo=timezone.utc),
        ),
        SimpleNamespace(
            side="sell",
            quantity=Decimal("10"),
            price=Decimal("108"),
            commission=Decimal("0"),
            timestamp=datetime(2026, 9, 12, 15, tzinfo=timezone.utc),
        ),
    ]
    adapter = SimulateSnapshotAdapter(
        segments=[TECH],
        plans_fetcher=lambda _segment, _session: [_plan_stub(simulated_fills=fills)],
        event_fetcher=lambda _session, _symbols: [],
    )

    rows = adapter.compute("segment=information technology", SESSION).payload["rows"]

    assert [row["pnl"] for row in rows] == [0.0, 80.0]
    assert all(row["source"] == "simulated_fill" for row in rows)


def test_simulation_adapter_is_honestly_empty_without_fills() -> None:
    adapter = SimulateSnapshotAdapter(
        segments=[TECH],
        plans_fetcher=lambda _segment, _session: [_plan_stub()],
        event_fetcher=lambda _session, _symbols: [],
    )

    rows = adapter.compute("segment=information technology", SESSION).payload["rows"]

    assert rows == []


def test_simulation_requires_the_full_time_stop_window(monkeypatch) -> None:
    plan = _plan_stub()
    monkeypatch.setattr(adapters_module, "_plans", lambda _segment, _session: [plan])
    monkeypatch.setattr(
        adapters_module,
        "_forward_bars",
        lambda _symbol, _start, _end: [object()],
    )
    monkeypatch.setattr(
        "openbb_techtrade.execution.broker.simulate",
        lambda *_args: (_ for _ in ()).throw(AssertionError("premature simulation")),
    )

    assert adapters_module._simulated_plans(TECH, SESSION) == []


def test_audit_adapter_materializes_replay_forward_contract() -> None:
    fills = [
        SimpleNamespace(
            side="buy",
            quantity=Decimal("10"),
            price=Decimal("100"),
            commission=Decimal("0"),
        ),
        SimpleNamespace(
            side="sell",
            quantity=Decimal("10"),
            price=Decimal("108"),
            commission=Decimal("0"),
        ),
    ]
    adapter = AuditSnapshotAdapter(
        segments=[TECH],
        plans_fetcher=lambda _segment, _session: [
            _plan_stub(
                simulated_fills=fills,
                validation={"oos_metrics": {"cagr": 0.10, "sharpe": 1.25}},
            )
        ],
        event_fetcher=lambda _session, _symbols: [],
    )

    row = adapter.compute("segment=information technology", SESSION).payload["rows"][0]

    assert {
        "bar_date",
        "replay_cagr",
        "replay_sharpe",
        "forward_pnl",
        "forward_return",
    } <= row.keys()
    assert row["replay_cagr"] == 0.10
    assert row["replay_sharpe"] == 1.25
    assert row["forward_pnl"] == 80.0
    assert row["forward_return"] == 0.08


def test_audit_adapter_skips_plans_without_forward_fills() -> None:
    adapter = AuditSnapshotAdapter(
        segments=[TECH],
        plans_fetcher=lambda _segment, _session: [_plan_stub()],
        event_fetcher=lambda _session, _symbols: [],
    )

    rows = adapter.compute("segment=information technology", SESSION).payload["rows"]

    assert rows == []


def test_snapshot_tuning_disables_persistence(monkeypatch) -> None:
    captured: list[bool] = []

    async def fake_tune(*, segment, as_of, persist):
        captured.append(persist)
        return SimpleNamespace(results={"segment": segment, "as_of": as_of})

    monkeypatch.setattr(
        "openbb_techtrade.tuning.tune_router.tune",
        fake_tune,
    )

    adapters_module._tuning(TECH, SESSION)

    assert captured == [False]
