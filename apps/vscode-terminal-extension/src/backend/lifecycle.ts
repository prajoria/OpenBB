// Back-end lifecycle for the OpenBB Terminal VS Code extension (#1819).
//
// Spawns `openbb-api --host 127.0.0.1 --port <port>` per ADR
// `docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`. Uses
// `/widgets.json` for readiness and periodic health polls.
//
// AUTH INVARIANTS (ADR 2026-08-04-vscode-terminal-webview-auth §5): this
// module never sets a bearer auth header and never appends a token query
// parameter to any URL. The extension talks to loopback-only 127.0.0.1,
// so bearer auth would add attack surface without adding trust.

import * as childProcess from "child_process";
import * as path from "path";
import * as vscode from "vscode";

import {
  BackendEvent,
  BackendState,
  initialState,
  transition,
} from "./state";

export interface BackendConfig {
  pythonPath?: string;
  port: number;
  apiBase: string;
  onStateChange: (state: BackendState) => void;
  outputChannel: vscode.OutputChannel;
}

const READINESS_TIMEOUT_MS = 60_000;
const READINESS_POLL_MS = 2_000;
const HEALTH_POLL_MS = 10_000;
const STOP_GRACE_MS = 3_000;
const SPAWNED_STATE_KEY = "openbb.backend.spawnedByUs";
const SPAWNED_PID_KEY = "openbb.backend.pid";

export class BackendLifecycle implements vscode.Disposable {
  private readonly context: vscode.ExtensionContext;
  private readonly cfg: BackendConfig;
  private child: childProcess.ChildProcess | undefined;
  private state: BackendState;
  private readonly listeners: Array<(s: BackendState) => void> = [];

  constructor(context: vscode.ExtensionContext, config: BackendConfig) {
    this.context = context;
    this.cfg = config;
    this.state = initialState(config.port);
  }

  getState(): BackendState {
    return this.state;
  }

  subscribe(listener: (s: BackendState) => void): vscode.Disposable {
    this.listeners.push(listener);
    return {
      dispose: () => {
        const idx = this.listeners.indexOf(listener);
        if (idx >= 0) {
          this.listeners.splice(idx, 1);
        }
      },
    };
  }

  dispose(): void {
    void this.stop().catch(() => undefined);
  }

  private dispatch(event: BackendEvent): void {
    this.state = transition(this.state, event);
    try {
      this.cfg.onStateChange(this.state);
    } catch (err) {
      this.log(`onStateChange threw: ${String(err)}`);
    }
    for (const listener of this.listeners) {
      try {
        listener(this.state);
      } catch (err) {
        this.log(`listener threw: ${String(err)}`);
      }
    }
  }

  private log(msg: string): void {
    this.cfg.outputChannel.appendLine(msg);
  }

  private async probeReadiness(): Promise<boolean> {
    try {
      const res = await fetch(`${this.cfg.apiBase}/widgets.json`, {
        method: "GET",
      });
      if (res.status !== 200) {
        return false;
      }
      const body = await res.text();
      try {
        JSON.parse(body);
      } catch {
        return false;
      }
      return true;
    } catch {
      return false;
    }
  }

  private resolveOpenbbApi(): string {
    const configured = this.cfg.pythonPath?.trim();
    const interpreter =
      configured && configured.length > 0 ? configured : "python";
    const pyDir = path.dirname(interpreter);
    const isWin = process.platform === "win32";
    const binName = isWin ? "openbb-api.exe" : "openbb-api";
    if (!pyDir || pyDir === "." || pyDir === "") {
      return binName;
    }
    return path.join(pyDir, isWin ? "Scripts" : "bin", binName);
  }

  async start(): Promise<void> {
    if (this.state.status === "running" || this.state.status === "starting") {
      this.log(`start() ignored — status=${this.state.status}`);
      return;
    }

    this.dispatch({ type: "SPAWN_REQUESTED" });

    if (await this.probeReadiness()) {
      this.log(
        `attached to existing backend at ${this.cfg.apiBase} (not spawning)`,
      );
      await this.context.workspaceState.update(SPAWNED_STATE_KEY, false);
      await this.context.workspaceState.update(SPAWNED_PID_KEY, undefined);
      this.state = { ...this.state, spawnedByUs: false };
      this.dispatch({ type: "SPAWN_SUCCEEDED", pid: -1 });
      return;
    }

    const bin = this.resolveOpenbbApi();
    this.log(`spawning ${bin} --host 127.0.0.1 --port ${this.cfg.port}`);

    let child: childProcess.ChildProcess;
    try {
      child = childProcess.spawn(
        bin,
        ["--host", "127.0.0.1", "--port", String(this.cfg.port)],
        { stdio: ["ignore", "pipe", "pipe"], windowsHide: true },
      );
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      this.log(`spawn failed: ${msg}`);
      this.dispatch({ type: "SPAWN_FAILED", error: msg });
      return;
    }

    this.child = child;
    child.stdout?.on("data", (buf: Buffer) => {
      this.log(`[stdout] ${buf.toString("utf8").trimEnd()}`);
    });
    child.stderr?.on("data", (buf: Buffer) => {
      this.log(`[stderr] ${buf.toString("utf8").trimEnd()}`);
    });
    child.on("error", (err: Error) => {
      this.log(`child error: ${err.message}`);
      this.dispatch({ type: "SPAWN_FAILED", error: err.message });
      this.child = undefined;
    });
    child.on("exit", (code, signal) => {
      this.log(`child exited code=${String(code)} signal=${String(signal)}`);
      this.child = undefined;
      if (this.state.status !== "stopped") {
        this.dispatch({ type: "STOPPED" });
      }
    });

    await this.context.workspaceState.update(SPAWNED_STATE_KEY, true);
    await this.context.workspaceState.update(SPAWNED_PID_KEY, child.pid);
    this.state = { ...this.state, spawnedByUs: true };

    const start = Date.now();
    while (Date.now() - start < READINESS_TIMEOUT_MS) {
      if (await this.probeReadiness()) {
        const pid = child.pid ?? 0;
        this.log(`backend ready on ${this.cfg.apiBase} (pid=${pid})`);
        this.dispatch({ type: "SPAWN_SUCCEEDED", pid });
        return;
      }
      await sleep(READINESS_POLL_MS);
    }

    const timeoutMsg = `readiness probe timed out after ${READINESS_TIMEOUT_MS}ms`;
    this.log(timeoutMsg);
    await this.killChild(child);
    this.dispatch({ type: "SPAWN_FAILED", error: timeoutMsg });
  }

  async stop(): Promise<void> {
    const spawnedByUs =
      this.state.spawnedByUs ??
      this.context.workspaceState.get<boolean>(SPAWNED_STATE_KEY, false);
    if (!spawnedByUs) {
      this.log("attached to external backend; not stopping");
      this.dispatch({ type: "STOPPED" });
      return;
    }

    const child = this.child;
    if (!child || child.pid === undefined) {
      this.dispatch({ type: "STOPPED" });
      return;
    }

    this.dispatch({ type: "STOP_REQUESTED" });
    await this.killChild(child);
    this.dispatch({ type: "STOPPED" });
    await this.context.workspaceState.update(SPAWNED_STATE_KEY, false);
    await this.context.workspaceState.update(SPAWNED_PID_KEY, undefined);
  }

  private async killChild(child: childProcess.ChildProcess): Promise<void> {
    const pid = child.pid;
    if (pid === undefined) {
      return;
    }
    if (process.platform === "win32") {
      await execFileAsync("taskkill", ["/pid", String(pid)]);
    } else {
      try {
        child.kill("SIGTERM");
      } catch (err) {
        this.log(`SIGTERM failed: ${String(err)}`);
      }
    }
    const graceStart = Date.now();
    while (Date.now() - graceStart < STOP_GRACE_MS) {
      if (child.exitCode !== null || child.signalCode !== null) {
        return;
      }
      await sleep(200);
    }
    if (process.platform === "win32") {
      await execFileAsync("taskkill", ["/pid", String(pid), "/F"]);
    } else {
      try {
        child.kill("SIGKILL");
      } catch (err) {
        this.log(`SIGKILL failed: ${String(err)}`);
      }
    }
  }

  async healthPoll(): Promise<void> {
    const ok = await this.probeReadiness();
    if (ok) {
      this.dispatch({ type: "HEALTH_OK" });
    } else {
      this.dispatch({
        type: "HEALTH_FAILED",
        error: "widgets.json probe failed",
      });
    }
  }

  startHealthMonitor(): vscode.Disposable {
    const timer = setInterval(() => {
      if (this.state.status !== "running") {
        return;
      }
      void this.healthPoll();
    }, HEALTH_POLL_MS);
    return { dispose: () => clearInterval(timer) };
  }
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function execFileAsync(cmd: string, args: string[]): Promise<void> {
  return new Promise((resolve) => {
    childProcess.execFile(cmd, args, () => {
      resolve();
    });
  });
}
