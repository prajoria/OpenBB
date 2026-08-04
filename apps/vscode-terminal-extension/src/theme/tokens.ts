/**
 * Theme token bridge — dark theme first (#1815).
 *
 * `CORE_TOKEN_MAP` pairs OpenBB-neutral CSS custom properties (--color-*)
 * with VS Code's editor theme variables (--vscode-*). The webview reads
 * the mapped --vscode-* values from `getComputedStyle(document.body)` and
 * writes them onto `document.documentElement` as --color-* variables, so
 * the layout / widget code stays theme-agnostic.
 *
 * `DARK_FALLBACK` provides VS Code Dark+ defaults for the extension host
 * side (where computed styles are unavailable). Light + high-contrast
 * palettes land in #1837.
 */

export type ThemeTokens = Record<string, string>;

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
