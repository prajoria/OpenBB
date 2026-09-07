"""Dedicated worker process and CLI for the OpenBB jobs service.

Production execution occurs only here. The REST API is a control plane that
enqueues, lists, cancels, and reports on runs, but it never resolves or calls
a job handler. ``JobWorker`` claims durable runs, executes their allowlisted
handlers, and records the outcome.

While a handler runs synchronously (potentially for minutes), a background
heartbeat thread keeps refreshing the worker's lease more frequently than
``JobService.run_lease_timeout`` so the store never mistakes a live run for
an abandoned one.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import signal
import socket
import sys
import threading
import time
from datetime import datetime, timedelta
from typing import Any

from openbb_core.app.extension_loader import ExtensionLoader
from openbb_core.app.jobs.models import JobContext, JobRun
from openbb_core.app.jobs.registry import JobRegistry
from openbb_core.app.service.job_service import JobService
from pydantic import BaseModel, ConfigDict
from uuid_extensions import uuid7str

logger = logging.getLogger("uvicorn.error")

DEFAULT_POLL_SECONDS = 5.0
MIN_HEARTBEAT_SECONDS = 1.0
MAX_HEARTBEAT_SECONDS = 30.0
HEARTBEAT_LEASE_FRACTION = 3
HEARTBEAT_JOIN_TIMEOUT_SECONDS = 5.0


class JobOutcome(BaseModel):
    """Outcome of one claimed-and-executed run."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    job_name: str
    status: str


def default_worker_id() -> str:
    """Return a unique worker identifier for this process."""
    return f"{socket.gethostname()}-{os.getpid()}-{uuid7str()[:8]}"


class JobWorker:
    """Poll for due work, claim it, execute it, and record the outcome."""

    def __init__(
        self,
        *,
        service: JobService,
        worker_id: str | None = None,
        heartbeat_seconds: float | None = None,
        hostname: str | None = None,
    ) -> None:
        """Initialize a worker bound to a job service instance."""
        self._service = service
        self._worker_id = worker_id or default_worker_id()
        self._hostname = hostname or socket.gethostname()
        self._heartbeat_seconds = (
            heartbeat_seconds
            if heartbeat_seconds is not None
            else self._default_heartbeat_seconds(service.run_lease_timeout)
        )

    @property
    def worker_id(self) -> str:
        """Return this worker's identifier."""
        return self._worker_id

    @staticmethod
    def _default_heartbeat_seconds(run_lease_timeout: timedelta) -> float:
        """Derive a heartbeat interval strictly more frequent than the lease timeout."""
        lease_seconds = run_lease_timeout.total_seconds()
        return max(
            MIN_HEARTBEAT_SECONDS,
            min(MAX_HEARTBEAT_SECONDS, lease_seconds / HEARTBEAT_LEASE_FRACTION),
        )

    def run_once(
        self,
        now: datetime | None = None,
        stop_event: threading.Event | None = None,
    ) -> JobOutcome | None:
        """Run one scheduling-and-execution cycle; claim and run at most one job."""
        if stop_event is not None and stop_event.is_set():
            return None

        self._service.reconcile_definitions(now)
        self._service.heartbeat(self._worker_id, now, hostname=self._hostname)
        self._service.recover_abandoned_runs(now)
        self._service.enqueue_due(now)

        if stop_event is not None and stop_event.is_set():
            return None

        run = self._service.claim_next(self._worker_id, now=now)
        if run is None:
            return None

        return self._execute(run)

    def run_forever(
        self,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        stop_event: threading.Event | None = None,
    ) -> None:
        """Poll continuously until ``stop_event`` is set.

        Shutdown never interrupts an in-flight handler: the loop only checks
        for a stop request between cycles and while idly waiting to poll again.
        """
        event = stop_event or threading.Event()
        while not event.is_set():
            outcome = self.run_once(stop_event=event)
            if outcome is None:
                event.wait(poll_seconds)

    def _execute(self, run: JobRun) -> JobOutcome:
        """Execute one claimed run's handler and persist its outcome."""
        stop_heartbeat = threading.Event()
        heartbeat_thread: threading.Thread | None = None

        try:
            definition = self._service.registry.get(run.job_name)
            params = self._service.registry.validate_params(run.job_name, run.params)
            context = JobContext(
                run_id=run.run_id,
                job_name=run.job_name,
                attempt=run.attempt,
                max_attempts=run.max_attempts,
                worker_id=self._worker_id,
                scheduled_for=run.scheduled_for,
                started_at=run.started_at,
            )
            heartbeat_thread = self._start_heartbeat_thread(stop_heartbeat)
            result = definition.handler(context, params)
        except Exception as error:  # pylint: disable=broad-except
            self._stop_heartbeat_thread(stop_heartbeat, heartbeat_thread)
            failed = self._service.fail(run.run_id, error)
            return JobOutcome(
                run_id=failed.run_id, job_name=failed.job_name, status=failed.status
            )

        self._stop_heartbeat_thread(stop_heartbeat, heartbeat_thread)
        completed = self._service.complete(run.run_id, result)
        return JobOutcome(
            run_id=completed.run_id,
            job_name=completed.job_name,
            status=completed.status,
        )

    def _start_heartbeat_thread(
        self, stop_event: threading.Event
    ) -> threading.Thread | None:
        """Start a background thread that heartbeats faster than the lease timeout.

        Returns ``None`` (no thread started) when continuous heartbeating is
        disabled, in which case only the heartbeat recorded at claim time
        protects the run from recovery.
        """
        if not self._heartbeat_seconds:
            return None

        thread = threading.Thread(
            target=self._heartbeat_loop,
            args=(stop_event,),
            name=f"jobs-heartbeat-{self._worker_id}",
            daemon=True,
        )
        thread.start()
        return thread

    def _stop_heartbeat_thread(
        self, stop_event: threading.Event, thread: threading.Thread | None
    ) -> None:
        """Signal and join the heartbeat thread, if one was started."""
        stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=HEARTBEAT_JOIN_TIMEOUT_SECONDS)

    def _heartbeat_loop(self, stop_event: threading.Event) -> None:
        """Refresh the worker heartbeat until ``stop_event`` is set."""
        while not stop_event.wait(self._heartbeat_seconds):
            try:
                self._service.heartbeat(self._worker_id, hostname=self._hostname)
            except Exception:  # pylint: disable=broad-except
                # A heartbeat failure must never crash or interrupt the
                # in-flight handler; the next tick or claim-time heartbeat
                # will retry.
                logger.exception("Heartbeat failed for worker %s", self._worker_id)


def _build_registry() -> JobRegistry:
    """Discover job definitions from installed openbb_job_extension providers."""
    return ExtensionLoader().build_job_registry()


def _build_service(registry: JobRegistry | None = None) -> JobService:
    """Build a job service using discovered (or supplied) job definitions."""
    return JobService(registry=registry if registry is not None else _build_registry())


def _wait_for_terminal_run(
    service: JobService,
    run_id: str,
    *,
    poll_seconds: float = 0.5,
    timeout_seconds: float | None = None,
) -> JobRun:
    """Poll a run until it reaches a terminal state."""
    terminal = {"succeeded", "succeeded_with_warnings", "failed", "cancelled"}
    deadline = None if timeout_seconds is None else time.monotonic() + timeout_seconds

    while True:
        run = service.get_run(run_id)
        if run.status in terminal:
            return run
        if deadline is not None and time.monotonic() >= deadline:
            return run
        time.sleep(poll_seconds)


def cmd_list(_args: argparse.Namespace) -> int:
    """Print registered job definitions and their schedule state."""
    service = _build_service()
    for definition in service.list_definitions():
        state = "enabled" if definition.enabled else "disabled"
        next_run = definition.next_run_at.isoformat() if definition.next_run_at else "-"
        print(  # noqa: T201
            f"{definition.name}\t{state}\tnext_run={next_run}\t{definition.description}"
        )
    return 0


def cmd_trigger(args: argparse.Namespace) -> int:
    """Enqueue a manual run for a registered job, optionally waiting for it."""
    service = _build_service()
    params: dict[str, Any] = json.loads(args.params_json) if args.params_json else {}

    run = service.enqueue(args.job_name, params)
    print(f"queued run_id={run.run_id} status={run.status}")  # noqa: T201

    if not args.wait:
        return 0

    final_run = _wait_for_terminal_run(service, run.run_id)
    print(f"final run_id={final_run.run_id} status={final_run.status}")  # noqa: T201
    return 0 if final_run.status in {"succeeded", "succeeded_with_warnings"} else 1


def cmd_worker(args: argparse.Namespace) -> int:
    """Run the worker in once mode or continuously until interrupted."""
    service = _build_service()
    worker = JobWorker(service=service)

    if args.once:
        worker.run_once()
        return 0

    stop_event = threading.Event()

    def _handle_signal(_signum: int, _frame: Any) -> None:
        """Request a clean shutdown on interrupt/terminate signals."""
        stop_event.set()

    signal.signal(signal.SIGINT, _handle_signal)
    if hasattr(signal, "SIGTERM"):
        signal.signal(signal.SIGTERM, _handle_signal)

    worker.run_forever(poll_seconds=args.poll_seconds, stop_event=stop_event)
    return 0


def _build_parser() -> argparse.ArgumentParser:
    """Build the ``openbb-jobs`` argument parser."""
    parser = argparse.ArgumentParser(prog="openbb-jobs")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("list", help="List registered job definitions").set_defaults(
        func=cmd_list
    )

    trigger_parser = subparsers.add_parser(
        "trigger", help="Manually enqueue a registered job"
    )
    trigger_parser.add_argument("job_name")
    trigger_parser.add_argument(
        "--params-json", default=None, help="JSON-encoded job parameters"
    )
    trigger_parser.add_argument(
        "--wait", action="store_true", help="Wait for the run to reach a terminal state"
    )
    trigger_parser.set_defaults(func=cmd_trigger)

    worker_parser = subparsers.add_parser("worker", help="Run the durable jobs worker")
    worker_parser.add_argument(
        "--once",
        action="store_true",
        help="Perform one scheduling and execution drain, then exit",
    )
    worker_parser.add_argument(
        "--poll-seconds",
        type=float,
        default=DEFAULT_POLL_SECONDS,
        help="Seconds to wait between empty polling cycles",
    )
    worker_parser.set_defaults(func=cmd_worker)

    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``openbb-jobs`` console script."""
    parser = _build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
