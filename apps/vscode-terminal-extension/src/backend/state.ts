// Pure reducer for the OpenBB back-end lifecycle state machine (#1819).
//
// Zero VS Code imports and zero side effects so it can be unit-tested
// with node:test alone. See ADR
// `docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md` §2.3:
// two consecutive HEALTH_FAILED transitions must move us to `error`.

export type BackendStatus = "stopped" | "starting" | "running" | "error";

export interface BackendState {
  status: BackendStatus;
  pid?: number;
  port: number;
  lastHealthAt?: Date;
  lastError?: string;
  consecutiveHealthFailures?: number;
  spawnedByUs?: boolean;
}

export type BackendEvent =
  | { type: "SPAWN_REQUESTED" }
  | { type: "SPAWN_SUCCEEDED"; pid: number }
  | { type: "SPAWN_FAILED"; error: string }
  | { type: "HEALTH_OK" }
  | { type: "HEALTH_FAILED"; error: string }
  | { type: "STOP_REQUESTED" }
  | { type: "STOPPED" };

export function initialState(port: number): BackendState {
  return { status: "stopped", port, consecutiveHealthFailures: 0 };
}

export function transition(
  current: BackendState,
  event: BackendEvent,
): BackendState {
  switch (event.type) {
    case "SPAWN_REQUESTED":
      return {
        ...current,
        status: "starting",
        lastError: undefined,
        consecutiveHealthFailures: 0,
      };
    case "SPAWN_SUCCEEDED":
      return {
        ...current,
        status: "running",
        pid: event.pid,
        lastError: undefined,
        consecutiveHealthFailures: 0,
        lastHealthAt: new Date(),
      };
    case "SPAWN_FAILED":
      return {
        ...current,
        status: "error",
        lastError: event.error,
        pid: undefined,
      };
    case "HEALTH_OK":
      return {
        ...current,
        status: "running",
        lastHealthAt: new Date(),
        consecutiveHealthFailures: 0,
        lastError: undefined,
      };
    case "HEALTH_FAILED": {
      const fails = (current.consecutiveHealthFailures ?? 0) + 1;
      if (fails >= 2) {
        return {
          ...current,
          status: "error",
          lastError: event.error,
          consecutiveHealthFailures: fails,
        };
      }
      return {
        ...current,
        lastError: event.error,
        consecutiveHealthFailures: fails,
      };
    }
    case "STOP_REQUESTED":
      // Stopping is asynchronous; STOPPED carries the terminal transition.
      return current;
    case "STOPPED":
      return {
        ...current,
        status: "stopped",
        pid: undefined,
        consecutiveHealthFailures: 0,
      };
    default:
      return current;
  }
}
