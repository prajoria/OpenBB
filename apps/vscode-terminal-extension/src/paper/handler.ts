// Paper trading order handler (#1835).
//
// Wires the openbb.paperBuyActive / openbb.paperSellActive commands to
// a POST against the backend's paper-order endpoint. Follows the Phase 0
// ADR-#1809 auth rules — no bearer auth header, no token query param —
// the backend runs on loopback and trusts local callers.
//
// The backend endpoint may not exist in the running api yet; a 404 is
// treated as a "recorded locally" info-message rather than an error so
// the keybindings remain useful during backend rollout.

import type * as vscode from "vscode";
import type { SymbolContext } from "../symbol/context";

export type PaperOrderSide = "BUY" | "SELL";

export interface PaperOrderResult {
  ok: boolean;
  message: string;
  endpoint?: string;
}

export interface PlaceOrderOptions {
  quantity?: number;
  confirmOverride?: boolean;
}

export interface PaperOrderHandlerConfig {
  apiBase: string;
  symbolContext: Pick<SymbolContext, "getActiveSymbol">;
  outputChannel: Pick<vscode.OutputChannel, "appendLine">;
  confirmByDefault?: boolean;
  /** Injectable fetch — defaults to globalThis.fetch. */
  fetchImpl?: (url: string, init?: unknown) => Promise<{
    status: number;
    json?: () => Promise<unknown>;
    text?: () => Promise<string>;
  }>;
  /**
   * Injectable confirmation dialog — defaults to
   * vscode.window.showWarningMessage in modal mode. Returning "Yes" is
   * confirmation; anything else cancels.
   */
  confirmImpl?: (message: string) => Promise<string | undefined>;
}

const ENDPOINT_PATH = "/api/v1/portfolio_intel/paper/order";

export class PaperOrderHandler {
  private readonly apiBase: string;
  private readonly symbolContext: Pick<SymbolContext, "getActiveSymbol">;
  private readonly outputChannel: Pick<vscode.OutputChannel, "appendLine">;
  private readonly confirmByDefault: boolean;
  private readonly fetchImpl: NonNullable<PaperOrderHandlerConfig["fetchImpl"]>;
  private readonly confirmImpl: NonNullable<PaperOrderHandlerConfig["confirmImpl"]>;

  constructor(config: PaperOrderHandlerConfig) {
    this.apiBase = config.apiBase.replace(/\/+$/, "");
    this.symbolContext = config.symbolContext;
    this.outputChannel = config.outputChannel;
    this.confirmByDefault = config.confirmByDefault !== false;
    this.fetchImpl =
      config.fetchImpl ??
      ((url, init) =>
        (globalThis as unknown as {
          fetch: (u: string, i?: unknown) => Promise<{
            status: number;
            json?: () => Promise<unknown>;
            text?: () => Promise<string>;
          }>;
        }).fetch(url, init));
    this.confirmImpl =
      config.confirmImpl ??
      (async (message: string) => {
        // Late-bind vscode so tests importing this module without the
        // vscode host don't crash on import.
        // eslint-disable-next-line @typescript-eslint/no-require-imports
        const v = require("vscode") as typeof vscode;
        return (await v.window.showWarningMessage(
          message,
          { modal: true },
          "Yes",
        )) as string | undefined;
      });
  }

  async placeOrder(
    side: PaperOrderSide,
    opts?: PlaceOrderOptions,
  ): Promise<PaperOrderResult> {
    const symbol = this.symbolContext.getActiveSymbol();
    if (!symbol) {
      return { ok: false, message: "No active symbol" };
    }

    const shouldConfirm =
      opts?.confirmOverride === true || this.confirmByDefault;
    if (shouldConfirm) {
      const answer = await this.confirmImpl(
        `Place PAPER ${side} order for ${symbol}?`,
      );
      if (answer !== "Yes") {
        return { ok: false, message: "Cancelled by user" };
      }
    }

    const payload = {
      symbol,
      side,
      quantity: opts?.quantity ?? 1,
      orderType: "MARKET" as const,
    };
    const endpoint = `${this.apiBase}${ENDPOINT_PATH}`;

    let status = 0;
    let bodyText = "";
    try {
      const res = await this.fetchImpl(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      status = res.status;
      if (res.text) {
        try {
          bodyText = await res.text();
        } catch {
          bodyText = "";
        }
      }
    } catch (err) {
      const message = `Error: ${err instanceof Error ? err.message : String(err)}`;
      this.outputChannel.appendLine(
        `[paper] ${side} ${symbol} failed: ${message}`,
      );
      return { ok: false, message };
    }

    if (status === 200 || status === 201) {
      const message = `Paper ${side} order accepted for ${symbol}`;
      this.outputChannel.appendLine(
        `[paper] ${side} ${symbol} qty=${payload.quantity} -> ${status} @ ${endpoint}`,
      );
      return { ok: true, message, endpoint };
    }
    if (status === 404) {
      const json = JSON.stringify(payload);
      const message = `Paper trading endpoint not available in the running backend — order recorded locally: ${json}`;
      this.outputChannel.appendLine(
        `[paper] ${side} ${symbol} -> 404, recorded locally: ${json}`,
      );
      return { ok: false, message };
    }
    const message = `Error: HTTP ${status}${bodyText ? ` ${bodyText}` : ""}`;
    this.outputChannel.appendLine(
      `[paper] ${side} ${symbol} -> ${status} ${bodyText}`,
    );
    return { ok: false, message };
  }
}
