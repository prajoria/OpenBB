"""Dataset adapters for the canonical TechTrade EOD snapshot store."""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

from openbb_techtrade.models import Mover, MoverList
from openbb_techtrade.snapshot.adapters import (
    EventKind,
    MarketEvent,
    MoversSnapshotAdapter,
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
    assert store.retry_entity_keys(job.job_run_id) == [
        "segment=information technology"
    ]
    store.close()


def test_pyproject_advertises_movers_snapshot_adapter() -> None:
    pyproject = Path(__file__).resolve().parents[2] / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8")
    assert 'openbb_snapshot_dataset' in text
    assert (
        'techtrade_movers = '
        '"openbb_techtrade.snapshot.adapters:MoversSnapshotAdapter"'
    ) in text
