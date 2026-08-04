/**
 * Extension-host side of the theme bridge (#1815).
 */

import * as vscode from "vscode";
import { CORE_TOKEN_MAP, DARK_FALLBACK, ThemeTokens } from "./tokens";

export { CORE_TOKEN_MAP, DARK_FALLBACK };
export type { ThemeTokens };

export function collectThemeTokens(): ThemeTokens {
  return { ...DARK_FALLBACK };
}

export function registerThemeSync(
  context: vscode.ExtensionContext,
  postToWebviews: (tokens: ThemeTokens) => void,
): vscode.Disposable {
  const disposable = vscode.window.onDidChangeActiveColorTheme(() => {
    postToWebviews(collectThemeTokens());
  });
  context.subscriptions.push(disposable);
  return disposable;
}
