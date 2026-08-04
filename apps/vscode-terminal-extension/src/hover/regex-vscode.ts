// VS Code adapter for hover ticker detection (#1825). Imports `vscode`,
// so this module can only be loaded inside the extension host. The pure
// scanning function lives in `./regex.ts` and is what the unit tests
// exercise.

import * as vscode from "vscode";
import { findTickerInLine } from "./regex";

export interface TickerHit {
  symbol: string;
  range: vscode.Range;
}

/**
 * Return the ticker hit at `position` in `document`, else null.
 */
export function findTickerAt(
  document: vscode.TextDocument,
  position: vscode.Position,
): TickerHit | null {
  const line = document.lineAt(position.line).text;
  const raw = findTickerInLine(line, position.character);
  if (!raw) {
    return null;
  }
  return {
    symbol: raw.symbol,
    range: new vscode.Range(
      new vscode.Position(position.line, raw.start),
      new vscode.Position(position.line, raw.end),
    ),
  };
}
