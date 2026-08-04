// Symbol hover regex module (#1825) — pure, side-effect-free ticker
// detection.
//
// Two modes:
//   1. Assignment: `symbol = "AAPL"` / `ticker='MSFT'` — LHS symbol|ticker
//      and RHS is a quoted 2-5 UPPERCASE ticker.
//   2. Quoted literal: a 2-5 UPPERCASE ticker inside real ASCII quote
//      characters (e.g. `"NVDA"`) at the cursor.
//
// Rejected by construction:
//   - Bare identifiers (unquoted): API, URL, MAX, SQL, DDL — the regex
//     REQUIRES adjacent quote characters, so bare tokens never match.
//   - Single-letter tickers: "A" (min length 2).
//   - >=6-char runs: "GOOGLE" (max length 5).
//   - lowercase / mixed-case: "aapl", "Aapl" (character class is [A-Z]).
//
// The pure `findTickerInLine(text, col)` returns numeric offsets and is
// re-used by unit tests without loading the `vscode` module. The
// `findTickerAt` VS Code adapter lives in `./regex-vscode.ts` (which
// imports `vscode` and can only be loaded inside the extension host).

export interface RawTickerHit {
  symbol: string;
  start: number;
  end: number;
}

const QUOTED_RE = /(?<=["'])[A-Z]{2,5}(?=["'])/g;
const ASSIGN_RE = /\b(?:symbol|ticker)\s*=\s*["']([A-Z]{2,5})["']/g;

/**
 * Pure line-scan: return the ticker hit that spans column `col`, or null.
 * Assignment mode takes priority over bare quoted literal. Suitable for
 * unit tests — no `vscode` dependency.
 */
export function findTickerInLine(
  text: string,
  col: number,
): RawTickerHit | null {
  ASSIGN_RE.lastIndex = 0;
  for (let m = ASSIGN_RE.exec(text); m !== null; m = ASSIGN_RE.exec(text)) {
    const symbol = m[1];
    const rel = m[0].indexOf(symbol, m[0].indexOf("=") + 1);
    const start = m.index + rel;
    const end = start + symbol.length;
    if (col >= start && col <= end) {
      return { symbol, start, end };
    }
  }
  QUOTED_RE.lastIndex = 0;
  for (let m = QUOTED_RE.exec(text); m !== null; m = QUOTED_RE.exec(text)) {
    const symbol = m[0];
    const start = m.index;
    const end = start + symbol.length;
    if (col >= start && col <= end) {
      return { symbol, start, end };
    }
  }
  return null;
}
