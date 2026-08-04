// Panel <-> SymbolContext glue (#1823).

import * as vscode from "vscode";
import { SymbolContext } from "./context";

interface WidgetSymbolMessage {
  type: "symbolFromWidget";
  symbol: string;
}

function isWidgetSymbolMessage(m: unknown): m is WidgetSymbolMessage {
  if (typeof m !== "object" || m === null) {
    return false;
  }
  const rec = m as Record<string, unknown>;
  return rec.type === "symbolFromWidget" && typeof rec.symbol === "string";
}

export function attachSymbolBridge(
  panel: vscode.WebviewPanel,
  symbolContext: SymbolContext,
): vscode.Disposable {
  const registration = symbolContext.registerPanel(panel);
  const sub = panel.webview.onDidReceiveMessage((msg: unknown) => {
    if (isWidgetSymbolMessage(msg)) {
      void symbolContext.setSymbol(msg.symbol, "widget");
    }
  });
  return {
    dispose: () => {
      sub.dispose();
      registration.dispose();
    },
  };
}
