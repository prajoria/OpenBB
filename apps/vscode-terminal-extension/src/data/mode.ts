// Data-mode controller (#1820).
//
// Owns the fixture ↔ live transition driven by the backend lifecycle
// state. When the backend is `running`, widgets fetch from the local
// API; otherwise they render from bundled fixtures. See ADR
// `docs/Specs/adr/2026-08-04-vscode-terminal-backend-spawn.md`.

import type * as vscode from "vscode";
import type { BackendState } from "../backend/state";

export type DataMode = "fixture" | "live";

export interface DataModeControllerConfig {
  onModeChange?: (mode: DataMode) => void;
  outputChannel?: vscode.OutputChannel;
}

type PanelLike = {
  webview: { postMessage: (msg: unknown) => Thenable<boolean> | boolean };
};

export class DataModeController {
  private _mode: DataMode = "fixture";
  private readonly onModeChange?: (mode: DataMode) => void;
  private readonly outputChannel?: vscode.OutputChannel;
  private readonly panels = new Set<PanelLike>();

  constructor(config: DataModeControllerConfig = {}) {
    this.onModeChange = config.onModeChange;
    this.outputChannel = config.outputChannel;
  }

  get mode(): DataMode {
    return this._mode;
  }

  updateFromBackendState(state: BackendState): void {
    const next: DataMode = state.status === "running" ? "live" : "fixture";
    if (next === this._mode) return;
    this._mode = next;
    this.outputChannel?.appendLine(`[data-mode] -> ${next}`);
    if (this.onModeChange) this.onModeChange(next);
    for (const panel of this.panels) {
      postDataMode(panel, next);
    }
  }

  registerPanel(panel: PanelLike): void {
    this.panels.add(panel);
    postDataMode(panel, this._mode);
  }

  unregisterPanel(panel: PanelLike): void {
    this.panels.delete(panel);
  }
}

export function postDataMode(panel: PanelLike, mode: DataMode): void {
  try {
    void panel.webview.postMessage({ type: "dataModeChange", mode });
  } catch {
    // Panel may be disposed; ignore.
  }
}
