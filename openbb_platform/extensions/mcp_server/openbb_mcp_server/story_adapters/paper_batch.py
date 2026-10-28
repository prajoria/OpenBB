"""TechTrade order batches and paper-sink artifacts (#2332, N09b).

Routes under ``/api/v1/story``:

- ``POST /paper/batches/preview``: build an ``OrderBatch`` from typed
  tickets, gates and provenance, and return its content SHA, any failed
  gates and the operator's "type this at Fidelity" checklist. Pure.
- ``POST /runs/{run_id}/paper/batch_artifacts``: write the batch through
  TechTrade's ``PaperOrderSink`` (the paired Fidelity CSV and the six-sheet
  review workbook) and publish both into the run's artifact store.

Neither route submits anything or needs approval: these are review
documents, and a batch with failed gates is written so a reviewer can see
them. Submitting a batch to a paper engine is ``story_paper_prepare`` and an
approved ``story_paper_apply`` (N09a), which refuse a failed verdict.
"""

from __future__ import annotations

import copy
import tempfile
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, HTTPException, status
from openbb_core.app.service.auth_service import AuthService
from pydantic import AwareDatetime, Field, ValidationError

from openbb_mcp_server.story_adapters.artifacts import (
    ArtifactRecord,
    ArtifactStore,
    default_artifact_root,
)
from openbb_mcp_server.story_adapters.paper import Gate, Ticket, _Strict, _Text
from openbb_mcp_server.story_adapters.registry import RunStore, default_store_path

MAX_TICKETS = 50
RETENTION_DAYS = 30
_Symbol = Annotated[str, Field(pattern=r"^[A-Z][A-Z0-9./\-]{0,15}$")]
_Price = Annotated[
    Decimal, Field(gt=0, max_digits=20, decimal_places=8, allow_inf_nan=False)
]
_Weight = Annotated[
    Decimal, Field(ge=0, le=1, max_digits=12, decimal_places=8, allow_inf_nan=False)
]


class BatchTicket(Ticket):
    """A ticket as the Fidelity basket file carries it."""

    account_masked: Annotated[str, Field(pattern=r"^[*A-Za-z0-9_\-]{1,32}$")] | None = (
        None
    )


class BatchGate(Gate):
    """A gate with the reviewer's note."""

    notes: _Text = ""


class BatchPlan(_Strict):
    """Tickets, gates and provenance for one batch."""

    plan_id: Annotated[str, Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")]
    tickets: list[BatchTicket] = Field(min_length=1, max_length=MAX_TICKETS)
    verdict_gate_pass: bool = False
    verdict_gates: list[BatchGate] = Field(default_factory=list, max_length=20)
    pricing: dict[_Symbol, _Price] | None = Field(default=None, max_length=MAX_TICKETS)
    pre_execution_positions: dict[_Symbol, _Weight] | None = Field(
        default=None, max_length=200
    )
    generator_version: _Text = ""
    git_sha: _Text = ""
    generated_at: AwareDatetime | None = None


def build_batch(plan: BatchPlan) -> Any:
    """Construct TechTrade's ``OrderBatch``; its own validators run too."""
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.execution.order_sink import (
        OrderBatch,
        OrderTicket,
        PlanContext,
        VerdictGate,
    )

    return OrderBatch(
        tickets=tuple(OrderTicket(**t.model_dump()) for t in plan.tickets),
        plan_id=plan.plan_id,
        verdict_gate_pass=plan.verdict_gate_pass,
        generated_at=plan.generated_at or datetime.now(timezone.utc),
        pricing=plan.pricing,
        pre_execution_positions=plan.pre_execution_positions,
        plan_context=PlanContext(
            verdict_gates=tuple(
                VerdictGate(**g.model_dump()) for g in plan.verdict_gates
            ),
            generator_version=plan.generator_version,
            git_sha=plan.git_sha,
        ),
    )


def preview(plan: BatchPlan) -> dict[str, Any]:
    """Content SHA, failed gates and the operator's checklist."""
    batch = build_batch(plan)
    failed = [gate.name for gate in plan.verdict_gates if not gate.passed]
    checklist = [
        {
            "symbol": t.symbol,
            "action": t.action,
            "quantity": str(t.quantity),
            "order_type": t.order_type,
            "limit_price": str(t.limit_price) if t.limit_price is not None else None,
            "tif": t.tif,
        }
        for t in plan.tickets
    ]
    return {
        "batch_sha256": batch.sha256(),
        "sha_short": batch.sha_short(),
        "plan_id": plan.plan_id,
        "tickets": len(plan.tickets),
        "verdict_gate_pass": plan.verdict_gate_pass,
        "failed_gates": failed,
        # Only a passing verdict with no failed gate may be submitted (N09a).
        "executable": plan.verdict_gate_pass and not failed,
        "checklist": checklist,
    }


def sink_files(plan: BatchPlan) -> tuple[str, bytes, bytes]:
    """Write the batch with ``PaperOrderSink`` and return its SHA, CSV and XLSX."""
    # pylint: disable=import-outside-toplevel
    from openbb_techtrade.execution.order_sink import PaperOrderSink

    batch = build_batch(plan)
    with tempfile.TemporaryDirectory(prefix="story-batch-") as scratch:
        written = PaperOrderSink(Path(scratch)).write_batch(batch)
        return (
            written.batch_sha256,
            written.csv_path.read_bytes(),
            written.xlsx_path.read_bytes(),
        )


def _unprocessable(error: Exception) -> HTTPException:
    if isinstance(error, ValidationError):
        detail: Any = error.errors(
            include_url=False, include_context=False, include_input=False
        )
    else:
        detail = str(error)
    return HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, detail)


def build_router(runs: RunStore, artifacts: ArtifactStore, principal: str) -> APIRouter:
    """Return the batch routes bound to one principal."""
    router = APIRouter(prefix="/api/v1/story", tags=["story"])
    authenticated = [Depends(AuthService().auth_hook)]

    @router.post(
        "/paper/batches/preview",
        operation_id="story_paper_order_batch",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_paper_order_batch"}},
    )
    def story_paper_order_batch(plan: BatchPlan) -> dict[str, Any]:
        """Validate a TechTrade order batch; return its SHA, gates and checklist."""
        try:
            return preview(plan)
        except ValueError as error:
            raise _unprocessable(error) from error

    @router.post(
        "/runs/{run_id}/paper/batch_artifacts",
        operation_id="story_paper_batch_artifacts",
        dependencies=authenticated,
        openapi_extra={"mcp_config": {"name": "story_paper_batch_artifacts"}},
    )
    def story_paper_batch_artifacts(run_id: str, plan: BatchPlan) -> dict[str, Any]:
        """Write the Fidelity CSV and review workbook for a batch into a run."""
        run = runs.get(principal, run_id)
        if run is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Unknown run.")
        try:
            sha, csv_bytes, xlsx_bytes = sink_files(plan)
        except ValueError as error:
            raise _unprocessable(error) from error
        names = {
            "csv": f"fidelity-batch-{sha[:8]}",
            "workbook": f"batch-workbook-{sha[:8]}",
        }
        existing = {
            record.name: record
            for record in artifacts.list(principal, run_id=run_id)
            if record.name in names.values()
        }
        files = {
            "csv": ("table", "text/csv", "csv", csv_bytes),
            "workbook": (
                "workbook",
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                "xlsx",
                xlsx_bytes,
            ),
        }
        records: dict[str, ArtifactRecord] = {}
        # The workbook goes first, mirroring the sink: a run never holds an
        # uploadable CSV without its review workbook.
        for key in ("workbook", "csv"):
            name = names[key]
            if name in existing:
                records[key] = existing[name]
                continue
            kind, media_type, extension, payload = files[key]
            try:
                records[key] = artifacts.write(
                    principal,
                    run_id,
                    story_id=run.story_id,
                    name=name,
                    kind=kind,
                    media_type=media_type,
                    extension=extension,
                    payload=payload,
                    retention_days=RETENTION_DAYS,
                )
            except Exception as error:  # pylint: disable=broad-except
                raise HTTPException(status.HTTP_409_CONFLICT, str(error)) from error
        return {
            "batch_sha256": sha,
            "csv": records["csv"].model_dump(mode="json"),
            "workbook": records["workbook"].model_dump(mode="json"),
        }

    return router


def compose_story_paper_batch_app(
    source_app: FastAPI,
    *,
    principal: str,
    store_path: Path | None = None,
    artifact_root: Path | None = None,
) -> FastAPI:
    """Add the batch routes, bound to ``principal``, to an isolated app copy."""
    if not principal:
        raise ValueError("Story paper batches require an authenticated principal")
    db_path = store_path if store_path is not None else default_store_path()
    artifacts = ArtifactStore(
        artifact_root if artifact_root is not None else default_artifact_root(),
        db_path,
    )
    composed = copy.copy(source_app)
    composed.router = copy.copy(source_app.router)
    composed.router.middleware_stack = composed.router.app
    composed.middleware_stack = None
    composed.router.routes = list(source_app.router.routes)
    composed.include_router(build_router(RunStore(db_path), artifacts, principal))
    composed.openapi_schema = None
    return composed
