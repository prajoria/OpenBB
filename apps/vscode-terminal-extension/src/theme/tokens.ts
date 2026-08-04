/**
 * Theme token bridge — dark, light, high-contrast (#1815, #1837).
 */

export type ThemeTokens = Record<string, string>;

export type ThemeKind = "dark" | "light" | "high-contrast";

export const CORE_TOKEN_MAP: readonly (readonly [string, string])[] = [
  ["--color-background", "--vscode-editor-background"],
  ["--color-foreground", "--vscode-editor-foreground"],
  ["--color-surface", "--vscode-sideBar-background"],
  ["--color-border", "--vscode-panel-border"],
  ["--color-primary", "--vscode-button-background"],
  ["--color-primary-fg", "--vscode-button-foreground"],
  ["--color-accent", "--vscode-focusBorder"],
  ["--color-success", "--vscode-terminal-ansiGreen"],
  ["--color-error", "--vscode-terminal-ansiRed"],
  ["--color-warning", "--vscode-terminal-ansiYellow"],
] as const;

export const DARK_FALLBACK: ThemeTokens = {
  "--color-background": "#1e1e1e",
  "--color-foreground": "#d4d4d4",
  "--color-surface": "#252526",
  "--color-border": "#303031",
  "--color-primary": "#0e639c",
  "--color-primary-fg": "#ffffff",
  "--color-accent": "#007fd4",
  "--color-success": "#23d18b",
  "--color-error": "#f14c4c",
  "--color-warning": "#f5f543",
};

export const LIGHT_FALLBACK: ThemeTokens = {
  "--color-background": "#ffffff",
  "--color-foreground": "#333333",
  "--color-surface": "#f3f3f3",
  "--color-border": "#dddddd",
  "--color-primary": "#0e639c",
  "--color-primary-fg": "#ffffff",
  "--color-accent": "#007acc",
  "--color-success": "#388a34",
  "--color-error": "#a1260d",
  "--color-warning": "#bf8803",
};

export const HIGH_CONTRAST_FALLBACK: ThemeTokens = {
  "--color-background": "#000000",
  "--color-foreground": "#ffffff",
  "--color-surface": "#000000",
  "--color-border": "#6fc3df",
  "--color-primary": "#0000ff",
  "--color-primary-fg": "#ffffff",
  "--color-accent": "#f38518",
  "--color-success": "#00ff00",
  "--color-error": "#ff5555",
  "--color-warning": "#ffff00",
};

export function getFallbackForTheme(kind: ThemeKind): ThemeTokens {
  switch (kind) {
    case "light":
      return { ...LIGHT_FALLBACK };
    case "high-contrast":
      return { ...HIGH_CONTRAST_FALLBACK };
    case "dark":
    default:
      return { ...DARK_FALLBACK };
  }
}
