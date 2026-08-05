// Workspace-trust hardening — settings validators (#1856).
//
// Pure functions with no VS Code / Node side effects (beyond `path`),
// so they can be exercised from node:test without a harness. See
// docs/security.md for the trust posture these validators enforce.

import * as path from "node:path";

/**
 * Returns true if `hostname` is a loopback host after stripping any
 * surrounding IPv6 brackets and lowercasing. Accepts `127.0.0.1`,
 * `::1`, and `localhost`.
 */
export function isLoopbackHost(hostname: string): boolean {
  if (typeof hostname !== "string") {
    return false;
  }
  let h = hostname.trim().toLowerCase();
  if (h.startsWith("[") && h.endsWith("]")) {
    h = h.slice(1, -1);
  }
  return h === "127.0.0.1" || h === "::1" || h === "localhost";
}

export interface ValidationResult {
  ok: boolean;
  reason?: string;
}

/**
 * Validates a user-configured `openbb.apiBaseUrl`. The extension is
 * loopback-only (ADR 2026-08-04-vscode-terminal-webview-auth §5), so
 * we reject any non-loopback host or non-http(s) scheme up front.
 */
export function isSafeApiBaseUrl(raw: string): ValidationResult {
  let url: URL;
  try {
    url = new URL(raw);
  } catch {
    return { ok: false, reason: "invalid URL" };
  }
  if (url.protocol !== "http:" && url.protocol !== "https:") {
    return { ok: false, reason: "protocol must be http: or https:" };
  }
  let host = url.hostname;
  if (host.startsWith("[") && host.endsWith("]")) {
    host = host.slice(1, -1);
  }
  if (!isLoopbackHost(host)) {
    return {
      ok: false,
      reason: "hostname must be loopback (127.0.0.1, ::1, localhost)",
    };
  }
  return { ok: true };
}

export function isAbsolutePath(p: string): boolean {
  return path.isAbsolute(p);
}

/**
 * Validates a user-configured `openbb.pythonPath`. Must be absolute
 * and free of common shell metacharacters — the resolved path is
 * ultimately handed to `child_process.spawn`, and a workspace-scoped
 * override is a candidate for arbitrary code execution absent this
 * guard.
 */
export function isSafePythonPath(p: string): ValidationResult {
  if (!p) {
    return { ok: false, reason: "empty" };
  }
  if (!isAbsolutePath(p)) {
    return { ok: false, reason: "must be absolute path" };
  }
  if (/[;&|`]/.test(p)) {
    return { ok: false, reason: "contains shell metachars" };
  }
  return { ok: true };
}
