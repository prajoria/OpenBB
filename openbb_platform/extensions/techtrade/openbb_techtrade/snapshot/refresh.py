"""Standalone main-thread orchestration for post-close snapshot refreshes."""

from __future__ import annotations

import argparse
import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timezone
from importlib.metadata import entry_points
from typing import Protocol, cast
from uuid import uuid4

from openbb_techtrade.snapshot.job import (
    SnapshotJob,
    SnapshotJobState,
    SnapshotJobStore,
    utc_datetime,
)
from openbb_techtrade.snapshot.registry import (
    DEFAULT_DATASET_REGISTRY,
    SnapshotDatasetRegistry,
    SnapshotStoreRouter,
)
from openbb_techtrade.snapshot.semantics import last_completed_session
from openbb_techtrade.snapshot.store import (
    SnapshotRow,
    SnapshotStatus,
    SnapshotStore,
    canonical_key,
    get_default_snapshot_store,
    snapshot_input_hash,
)

ADAPTER_ENTRY_POINT_GROUP = "openbb_snapshot_dataset"
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComputedSnapshot:
    """One public, widget-shaped result produced by a dataset adapter."""

    payload: dict
    inputs: object
    engine_version: str
    payload_schema_version: str
    row_count: int | None = None


class SnapshotDatasetAdapter(Protocol):
    """Compute seam supplied by later dataset fan-out issues."""

    name: str

    def entity_keys(self) -> Iterable[str]:
        """Return the complete entity universe for a full refresh."""
        ...

    def compute(self, entity_key: str, as_of_session: date) -> ComputedSnapshot:
        """Compute one entity on the calling process's main thread."""
        ...


class _RefreshStore(SnapshotStore, SnapshotJobStore, Protocol):
    """Combined persistence contract required by orchestration."""

    def rows_for_job(self, job_run_id: str) -> list[SnapshotRow]:
        """Return snapshots produced by one job."""
        ...


class SnapshotRefreshOrchestrator:
    """Run one dataset with single-flight, keep-last-good, and targeted retry."""

    def __init__(
        self,
        router: SnapshotStoreRouter,
        registry: SnapshotDatasetRegistry,
        adapters: Mapping[str, SnapshotDatasetAdapter],
        *,
        clock: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
        job_id_factory: Callable[[], str] = lambda: uuid4().hex,
    ) -> None:
        self._router = router
        self._registry = registry
        self._adapters = {
            registry.require(name).name: adapter for name, adapter in adapters.items()
        }
        self._clock = clock
        self._job_id_factory = job_id_factory

    def run(self, dataset: str, *, retry_job_run_id: str | None = None) -> SnapshotJob:
        """Refresh a full dataset or only one prior run's failed keys."""
        definition = self._registry.require(dataset)
        adapter = self._adapters.get(definition.name)
        if adapter is None:
            raise ValueError("no snapshot compute adapter is installed for the dataset")
        store = cast(_RefreshStore, self._router.for_dataset(definition.name))
        now = utc_datetime(self._clock())
        job_run_id = self._job_id_factory()
        store.start_job(definition.name, job_run_id, started_at=now)
        completed = False
        try:
            as_of_session = last_completed_session(now)
            successes: list[tuple[str, str, date, str]] = []
            if retry_job_run_id is None:
                keys = list(
                    dict.fromkeys(canonical_key(key) for key in adapter.entity_keys())
                )
            else:
                prior = store.get_job(retry_job_run_id)
                if (
                    prior is None
                    or prior.dataset != definition.name
                    or prior.state
                    not in (SnapshotJobState.PARTIAL, SnapshotJobState.FAILED)
                ):
                    raise ValueError("retry source is not a job for this dataset")
                as_of_session = last_completed_session(prior.started_at)
                keys = store.retry_entity_keys(retry_job_run_id)
                if not keys:
                    raise ValueError("retry source has no failed entity keys")
                failed = set(keys)
                prior_rows = [
                    row
                    for row in store.rows_for_job(retry_job_run_id)
                    if row.entity_key not in failed
                    and row.validated
                    and row.status == SnapshotStatus.OK
                ]
                if len(prior_rows) != prior.n_ok:
                    raise ValueError("retry source success lineage is incomplete")
                sessions = {row.as_of_session for row in prior_rows}
                if len(sessions) > 1:
                    raise ValueError("retry source contains multiple session dates")
                if sessions and sessions != {as_of_session}:
                    raise ValueError("retry source session lineage is inconsistent")
                for row in prior_rows:
                    definition.read(row.payload, row.payload_schema_version)
                    store.stage(
                        definition.name,
                        row.entity_key,
                        as_of_session,
                        job_run_id,
                        row.payload,
                        status=SnapshotStatus.OK,
                        input_hash=row.input_hash,
                        row_count=row.row_count,
                        engine_version=row.engine_version,
                        payload_schema_version=row.payload_schema_version,
                    )
                    verdict = store.validate(
                        definition.name,
                        row.entity_key,
                        as_of_session,
                        job_run_id,
                    )
                    if not verdict.ok:
                        raise RuntimeError("retry_lineage_validation_failed")
                    successes.append(
                        (
                            definition.name,
                            row.entity_key,
                            as_of_session,
                            job_run_id,
                        )
                    )

            failures: dict[str, BaseException | str] = {}
            for raw_key in keys:
                try:
                    computed = adapter.compute(raw_key, as_of_session)
                    definition.read(computed.payload, computed.payload_schema_version)
                    input_hash = snapshot_input_hash(
                        computed.inputs, computed.engine_version
                    )
                    store.stage(
                        definition.name,
                        raw_key,
                        as_of_session,
                        job_run_id,
                        computed.payload,
                        status=SnapshotStatus.OK,
                        input_hash=input_hash,
                        row_count=computed.row_count,
                        engine_version=computed.engine_version,
                        payload_schema_version=computed.payload_schema_version,
                    )
                    verdict = store.validate(
                        definition.name, raw_key, as_of_session, job_run_id
                    )
                    if not verdict.ok:
                        failures[raw_key] = "validation_failed"
                        continue
                    successes.append(
                        (
                            definition.name,
                            canonical_key(raw_key),
                            as_of_session,
                            job_run_id,
                        )
                    )
                except Exception as exc:  # noqa: BLE001
                    failures[raw_key] = exc

            store.record_job_errors(job_run_id, failures)
            if failures:
                state = (
                    SnapshotJobState.PARTIAL if successes else SnapshotJobState.FAILED
                )
                job = store.finish_job(
                    job_run_id,
                    state,
                    n_ok=len(successes),
                    n_failed=len(failures),
                    error=(
                        "partial_failure"
                        if state == SnapshotJobState.PARTIAL
                        else "failed"
                    ),
                    finished_at=utc_datetime(self._clock()),
                )
                completed = True
                return job

            job = store.publish_job(
                job_run_id,
                successes,
                finished_at=utc_datetime(self._clock()),
                require_newer=retry_job_run_id is not None,
            )
            completed = True
            return job
        except BaseException as exc:
            current = store.get_job(job_run_id)
            if (
                not completed
                and current is not None
                and current.state == SnapshotJobState.RUNNING
            ):
                store.record_job_errors(job_run_id, {})
                store.finish_job(
                    job_run_id,
                    SnapshotJobState.FAILED,
                    n_ok=0,
                    n_failed=1,
                    error=exc,
                    finished_at=utc_datetime(self._clock()),
                )
            raise


def _load_adapters() -> dict[str, SnapshotDatasetAdapter]:
    """Load optional dataset adapters without importing consumer packages."""
    discovered: dict[str, SnapshotDatasetAdapter] = {}
    for entry in entry_points(group=ADAPTER_ENTRY_POINT_GROUP):
        loaded = entry.load()
        adapter = loaded() if isinstance(loaded, type) else loaded
        discovered[adapter.name] = adapter
    return discovered


def main(argv: list[str] | None = None) -> int:
    """Run one installed adapter in this standalone process's main thread."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", required=True)
    parser.add_argument("--retry-job-run-id")
    args = parser.parse_args(argv)
    adapters = _load_adapters()
    if args.dataset not in adapters:
        logger.error("snapshot adapter is not installed")
        return 2
    store = get_default_snapshot_store(allow_fallback=False)
    try:
        orchestrator = SnapshotRefreshOrchestrator(
            SnapshotStoreRouter(store, None, DEFAULT_DATASET_REGISTRY),
            DEFAULT_DATASET_REGISTRY,
            adapters,
        )
        job = orchestrator.run(args.dataset, retry_job_run_id=args.retry_job_run_id)
    finally:
        store.close()
    if job.state == SnapshotJobState.SUCCEEDED:
        return 0
    return 3 if job.state == SnapshotJobState.PARTIAL else 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
