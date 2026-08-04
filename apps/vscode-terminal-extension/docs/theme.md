# Theme token bridge

The VS Code terminal extension keeps its layouts and widgets theme-agnostic
by consuming a small set of neutral `--color-*` CSS custom properties.
Those neutral tokens are populated at runtime from VS Code's own
`--vscode-*` theme variables via the bridge shipped in #1815.

## Token mapping (dark theme first)

| Neutral token          | VS Code source variable        |
| ---------------------- | ------------------------------ |
| `--color-background`   | `--vscode-editor-background`   |
| `--color-foreground`   | `--vscode-editor-foreground`   |
| `--color-surface`      | `--vscode-sideBar-background`  |
| `--color-border`       | `--vscode-panel-border`        |
| `--color-primary`      | `--vscode-button-background`   |
| `--color-primary-fg`   | `--vscode-button-foreground`   |
| `--color-accent`       | `--vscode-focusBorder`         |
| `--color-success`      | `--vscode-terminal-ansiGreen`  |
| `--color-error`        | `--vscode-terminal-ansiRed`    |
| `--color-warning`      | `--vscode-terminal-ansiYellow` |

The canonical map lives in `src/theme/tokens.ts` (`CORE_TOKEN_MAP`). The
webview-side script `media/theme.js` duplicates the same list so it can
run as a plain browser script without a bundler.

## Fallback behavior

`DARK_FALLBACK` in `src/theme/tokens.ts` carries VS Code Dark+ hex values
for every `--color-*` key. The extension host posts these to freshly
created webviews so they render coherently before `getComputedStyle`
resolves the live theme, and re-posts them whenever
`vscode.window.onDidChangeActiveColorTheme` fires.

## TODO

- Light + high-contrast palettes: tracked in #1837.
