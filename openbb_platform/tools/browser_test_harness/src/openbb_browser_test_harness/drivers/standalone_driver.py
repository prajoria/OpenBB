"""Standalone HTTP driver (B1, #1723).

Spawns the widget_backend on a dynamically-allocated 127.0.0.1 port, hits each
step's endpoint via httpx, and returns StepResult observations.

Design spec: docs/superpowers/specs/2026-08-01-browser-test-harness-design.md §5.1

Key invariants (all P0/P1 fixes from the code review):

- **P0-2 subprocess/port management:** dynamic port allocation, readiness gate,
  process-group cleanup, crash-during-setup detection.
- **P0-3 auth-mode env safety:** subprocess env only (never os.environ), refuse
  to run if parent has conflicting PI_WIDGET_BACKEND_* set, only bind 127.0.0.1.
- **P2-9 n/a sentinel:** "widget_visible" and "not_blank" observations are the
  string ``"n/a"`` in standalone mode, never ``True``.
- **§10 silent-failure guard:** ``run_step`` checks ``Popen.poll()`` on every
  step; if the subprocess died, the step short-circuits with
  ``error="backend_down"``.
"""

from __future__ import annotations

import asyncio
import os
import signal
import socket
import subprocess
import sys
import time
from dataclasses import dataclass, field

import httpx

from ..steps import ActionKind, Step, StepResult


class HarnessSetupError(RuntimeError):
    """Raised when the harness cannot start safely."""


class BackendCrashedError(RuntimeError):
    """Raised when the spawned uvicorn crashed during setup or mid-run."""


def _allocate_port() -> int:
    """Ask the kernel for a free 127.0.0.1 port (bind 0 trick).

    Prevents port 6120 conflicts across concurrent CI shards and stale-run
    leaks (spec §5.1 P0-2).
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def _parent_auth_env_ok() -> tuple[bool, str]:
    """Refuse to run if parent env has conflicting PI_WIDGET_BACKEND_* set.

    Prevents silent auth disablement in a dev shell that happened to have
    production tokens loaded (spec §5.1 P0-3).

    Returns (ok, reason). If ok=False, ``reason`` names what to unset.
    """
    parent_mode = os.environ.get("PI_WIDGET_BACKEND_AUTH_MODE", "").strip()
    parent_token = os.environ.get("PI_WIDGET_BACKEND_TOKEN", "").strip()

    if parent_mode and parent_mode != "loopback-dev":
        return False, (
            f"parent PI_WIDGET_BACKEND_AUTH_MODE={parent_mode!r} conflicts with "
            "harness override. Unset it before running the harness."
        )
    if parent_token:
        return False, (
            "parent PI_WIDGET_BACKEND_TOKEN is set. The harness runs against a "
            "loopback-dev backend and must not run in a shell that has a "
            "production token loaded. Unset PI_WIDGET_BACKEND_TOKEN first."
        )
    return True, ""


@dataclass
class StandaloneDriver:
    """HTTP-only driver — no browser required.

    Usage::

        driver = StandaloneDriver()
        await driver.setup()
        try:
            for step in story.steps:
                result = await driver.run_step(step)
                ...
        finally:
            await driver.teardown()
    """

    #: Port the subprocess bound to (populated in setup())
    port: int = 0
    #: Base URL (populated in setup())
    base_url: str = ""
    #: Timeout for the readiness probe, seconds
    readiness_timeout_s: float = 10.0
    #: Timeout for each step's httpx call, seconds
    step_timeout_s: float = 5.0
    #: Subprocess handle (populated in setup())
    proc: subprocess.Popen[bytes] | None = field(default=None, repr=False)
    #: Client (populated in setup())
    client: httpx.AsyncClient | None = field(default=None, repr=False)

    async def setup(self) -> None:
        """Spawn uvicorn, wait for readiness, verify env is safe.

        Raises:
            HarnessSetupError: if parent env is unsafe.
            BackendCrashedError: if the subprocess died before /widgets.json
                came up.
        """
        ok, reason = _parent_auth_env_ok()
        if not ok:
            raise HarnessSetupError(reason)

        self.port = _allocate_port()
        self.base_url = f"http://127.0.0.1:{self.port}"

        # Subprocess env only — NEVER os.environ[...] = ... in parent.
        # This is the P0-3 fix: mutation is scoped to the child.
        child_env = os.environ.copy()
        child_env["PI_WIDGET_BACKEND_AUTH_MODE"] = "loopback-dev"

        # Process-group flags per OS.
        popen_kwargs: dict[str, object] = {
            "env": child_env,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
        }
        if sys.platform == "win32":
            popen_kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
        else:
            # POSIX: setsid so we can kill the whole group on teardown.
            popen_kwargs["start_new_session"] = True

        self.proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "uvicorn",
                "openbb_portfolio_intel.widget_backend.main:app",
                "--host",
                "127.0.0.1",
                "--port",
                str(self.port),
                "--log-level",
                "warning",
            ],
            **popen_kwargs,  # type: ignore[arg-type]
        )

        # Readiness gate: poll /widgets.json until it responds or timeout.
        # Also check Popen.poll() on every tick — crash-during-setup detection
        # (spec §5.1 P0-2).
        deadline = time.monotonic() + self.readiness_timeout_s
        interval_s = 0.1
        self.client = httpx.AsyncClient(base_url=self.base_url, timeout=self.step_timeout_s)
        last_error: Exception | None = None
        while time.monotonic() < deadline:
            # Did the subprocess die mid-startup?
            rc = self.proc.poll()
            if rc is not None:
                stderr = self.proc.stderr.read() if self.proc.stderr else b""
                await self.teardown()
                raise BackendCrashedError(
                    f"uvicorn exited with code {rc} during setup. "
                    f"stderr: {stderr.decode(errors='replace')[:2000]}"
                )
            try:
                resp = await self.client.get("/widgets.json")
                if resp.status_code == 200:
                    return
            except (httpx.ConnectError, httpx.RemoteProtocolError) as exc:
                last_error = exc
            await asyncio.sleep(interval_s)

        # Deadline exceeded.
        await self.teardown()
        raise HarnessSetupError(
            f"Backend did not become ready in {self.readiness_timeout_s}s "
            f"(last error: {last_error!r})"
        )

    async def teardown(self) -> None:
        """Kill the process group and close the client. Idempotent."""
        if self.client is not None:
            await self.client.aclose()
            self.client = None
        if self.proc is not None and self.proc.poll() is None:
            # SIGTERM first (CTRL_BREAK_EVENT on Windows), then SIGKILL after 5s.
            try:
                if sys.platform == "win32":
                    self.proc.send_signal(signal.CTRL_BREAK_EVENT)
                else:
                    os.killpg(os.getpgid(self.proc.pid), signal.SIGTERM)
            except (OSError, ProcessLookupError):
                # Process already gone.
                pass
            try:
                self.proc.wait(timeout=5.0)
            except subprocess.TimeoutExpired:
                self.proc.kill()
                self.proc.wait(timeout=2.0)
        self.proc = None

    async def run_step(self, step: Step) -> StepResult:
        """Execute one step and return the observation.

        Silent-failure guard: check Popen.poll() FIRST. If the subprocess is
        gone, short-circuit with error="backend_down" — never proceed to
        httpx and hang or silently pass (spec §10).
        """
        # Backend health check FIRST.
        if self.proc is None or self.proc.poll() is not None:
            return StepResult(
                step_id=step.id,
                ok=False,
                duration_ms=0,
                screenshot_path=None,
                observations={
                    "widget_visible": "n/a",
                    "not_blank": "n/a",
                },
                error="backend_down",
            )

        # ACTION-specific behavior.
        if step.endpoint is None:
            # NAVIGATE / SCREENSHOT with no endpoint — no-op in standalone mode.
            return StepResult(
                step_id=step.id,
                ok=True,
                duration_ms=0,
                screenshot_path=None,
                observations={
                    "widget_visible": "n/a",
                    "not_blank": "n/a",
                    "note": "endpoint=None; no-op in standalone mode",
                },
                error=None,
            )

        # Endpoint hit.
        assert self.client is not None
        path = step.endpoint if step.endpoint.startswith("/") else f"/{step.endpoint}"
        start = time.monotonic()
        try:
            resp = await self.client.get(path, params=step.params)
        except httpx.HTTPError as exc:
            return StepResult(
                step_id=step.id,
                ok=False,
                duration_ms=int((time.monotonic() - start) * 1000),
                screenshot_path=None,
                observations={"widget_visible": "n/a", "not_blank": "n/a"},
                error=f"http_error: {type(exc).__name__}",
            )
        duration_ms = int((time.monotonic() - start) * 1000)

        # Assertion: status matches.
        ok = resp.status_code == step.expected_status
        observations: dict[str, object] = {
            "status_code": resp.status_code,
            "widget_visible": "n/a",  # P2-9: cannot verify without a browser
            "not_blank": "n/a",  # P2-9
        }
        # For assertion-kind steps, also capture the body preview so a failure
        # is diagnostic. For observe-kind steps, just record row count.
        if step.action == ActionKind.ASSERT:
            try:
                observations["body_preview"] = str(resp.json())[:500]
            except ValueError:
                observations["body_preview"] = resp.text[:500]
        else:
            try:
                body = resp.json()
                if isinstance(body, list):
                    observations["row_count"] = len(body)
                elif isinstance(body, dict):
                    observations["key_count"] = len(body)
            except ValueError:
                observations["body_len"] = len(resp.text)

        return StepResult(
            step_id=step.id,
            ok=ok,
            duration_ms=duration_ms,
            screenshot_path=None,
            observations=observations,
            error=None
            if ok
            else f"expected_status={step.expected_status} got_status={resp.status_code}",
        )
