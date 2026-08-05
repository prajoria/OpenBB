/**
 * Extension-host side of the theme bridge (#1815, #1837).
 */

import * as vscode from "vscode";
import {
  CORE_TOKEN_MAP,
  DARK_FALLBACK,
  LIGHT_FALLBACK,
  HIGH_CONTRAST_FALLBACK,
  ThemeTokens,
  ThemeKind,
  getFallbackForTheme,
} from "./tokens";

export {
  CORE_TOKEN_MAP,
  DARK_FALLBACK,
  LIGHT_FALLBACK,
  HIGH_CONTRAST_FALLBACK,
  getFallbackForTheme,
};
export type { ThemeTokens, ThemeKind };

export function detectThemeKind(): ThemeKind {
  const active = vscode.window.activeColorTheme;
  const kind = active ? active.kind : vscode.ColorThemeKind.Dark;
  const HighContrastLight = (
    vscode.ColorThemeKind as unknown as { HighContrastLight?: number }
  ).HighContrastLight;
  if (kind === vscode.ColorThemeKind.Light) {
    return "light";
  }
  if (kind === vscode.ColorThemeKind.HighContrast) {
    return "high-contrast";
  }
  if (HighContrastLight !== undefined && kind === HighContrastLight) {
    return "high-contrast";
  }
  return "dark";
}

export function collectThemeTokens(kind?: ThemeKind): ThemeTokens {
  const resolved: ThemeKind = kind ?? detectThemeKind();
  return getFallbackForTheme(resolved);
}

export function registerThemeSync(
  context: vscode.ExtensionContext,
  postToWebviews: (tokens: ThemeTokens, kind: ThemeKind) => void,
): vscode.Disposable {
  const disposable = vscode.window.onDidChangeActiveColorTheme(() => {
    const kind = detectThemeKind();
    postToWebviews(collectThemeTokens(kind), kind);
  });
  context.subscriptions.push(disposable);
  return disposable;
}
