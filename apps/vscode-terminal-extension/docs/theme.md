# Theme token bridge

The VS Code terminal extension keeps its layouts and widgets theme-agnostic
by consuming a small set of neutral `--color-*` CSS custom properties.
Those neutral tokens are populated at runtime from VS Code's own
`--vscode-*` theme variables via the bridge shipped in #1815, with light
and high-contrast parity landing in #1837.

## Token mapping

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
webview-side script `media/theme.js` duplicates the same list.

## Three-way fallback (#1837)

`tokens.ts` ships three fallback palettes:

- `DARK_FALLBACK` — VS Code Dark+ defaults.
- `LIGHT_FALLBACK` — VS Code Light+ defaults.
- `HIGH_CONTRAST_FALLBACK` — WCAG-AA high-contrast palette.

`ThemeKind` is `"dark" | "light" | "high-contrast"`. `detectThemeKind()`
in `bridge.ts` maps `vscode.window.activeColorTheme.kind` to a
`ThemeKind`, folding both `HighContrast` and `HighContrastLight` into
`"high-contrast"`. `collectThemeTokens(kind?)` returns the correct
fallback via `getFallbackForTheme(kind)`. `registerThemeSync` re-posts
tokens + kind to webviews whenever the active theme changes.

## `data-openbb-theme` attribute (#1837)

`media/theme.js` reflects the active theme kind onto the document root:

```html
<html data-openbb-theme="dark">
```

Widget CSS can branch on this without inspecting individual colors. On
boot the webview posts `{ type: "themeReady", kind }` back to the host.

## Audit helper (#1837)

`src/theme/audit.ts` exposes `auditTheme(tokens, kind)` returning
`{ kind, missingTokens, contrastWarnings }` with WCAG-AA 4.5:1 contrast
verification via relative-luminance.
