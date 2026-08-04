// SOURCE-TEXT HEURISTIC ONLY. This does not introspect the Jupyter kernel's runtime variable values — that would require the Jupyter extension API or a debug adapter hook (out of scope; separate follow-up).
//
// Notebook symbol watcher (#1826). Scans notebook cell source text for
// `symbol = "AAPL"` / `ticker = "MSFT"` literal assignments and forwards
// the ticker to SymbolContext.setSymbol(sym, "notebook").

import * as vscode from "vscode";
import { SymbolContext } from "../symbol/context";

const SYMBOL_RE =
  /\b(?:symbol|ticker)\s*=\s*["']([A-Z]{2,5})(?::[A-Z]+)?["']/;

const DEBOUNCE_MS = 300;

interface LastSeen {
  symbol: string;
  lastMs: number;
}

function scanText(text: string): string | null {
  const m = text.match(SYMBOL_RE);
  return m ? m[1] : null;
}

function scanCells(cells: readonly vscode.NotebookCell[]): string | null {
  let last: string | null = null;
  for (const cell of cells) {
    const s = scanText(cell.document.getText());
    if (s) {
      last = s;
    }
  }
  return last;
}

export function registerNotebookSymbolWatcher(
  context: vscode.ExtensionContext,
  symbolContext: SymbolContext,
): vscode.Disposable {
  const perNotebook = new Map<string, LastSeen>();

  const broadcast = (uri: string, symbol: string): void => {
    const now = Date.now();
    const prev = perNotebook.get(uri);
    if (prev && prev.symbol === symbol && now - prev.lastMs < DEBOUNCE_MS) {
      return;
    }
    perNotebook.set(uri, { symbol, lastMs: now });
    void symbolContext.setSymbol(symbol, "notebook");
  };

  const openSub = vscode.workspace.onDidOpenNotebookDocument((doc) => {
    const sym = scanCells(doc.getCells());
    if (sym) {
      broadcast(doc.uri.toString(), sym);
    }
  });

  const changeSub = vscode.workspace.onDidChangeNotebookDocument((e) => {
    const changed: vscode.NotebookCell[] = [];
    for (const cc of e.cellChanges ?? []) {
      changed.push(cc.cell);
    }
    for (const cc of e.contentChanges ?? []) {
      for (const cell of cc.addedCells ?? []) {
        changed.push(cell);
      }
    }
    const sym = scanCells(changed);
    if (sym) {
      broadcast(e.notebook.uri.toString(), sym);
    }
  });

  return {
    dispose: () => {
      openSub.dispose();
      changeSub.dispose();
    },
  };
}
