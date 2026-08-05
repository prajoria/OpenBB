/**
 * Theme palette audit (#1837).
 */

import { CORE_TOKEN_MAP, ThemeTokens, ThemeKind } from "./tokens";

export interface ThemeAuditResult {
  kind: ThemeKind;
  missingTokens: string[];
  contrastWarnings: string[];
}

function parseHex(value: string): [number, number, number] | null {
  const trimmed = value.trim().replace(/^#/, "");
  if (trimmed.length !== 3 && trimmed.length !== 6) return null;
  const full =
    trimmed.length === 3
      ? trimmed.split("").map((c) => c + c).join("")
      : trimmed;
  if (!/^[0-9a-fA-F]{6}$/.test(full)) return null;
  return [
    parseInt(full.slice(0, 2), 16),
    parseInt(full.slice(2, 4), 16),
    parseInt(full.slice(4, 6), 16),
  ];
}

function channel(c: number): number {
  const s = c / 255;
  return s <= 0.03928 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
}

function relativeLuminance(rgb: [number, number, number]): number {
  const [r, g, b] = rgb;
  return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b);
}

export function contrastRatio(fg: string, bg: string): number | null {
  const fgRgb = parseHex(fg);
  const bgRgb = parseHex(bg);
  if (!fgRgb || !bgRgb) return null;
  const l1 = relativeLuminance(fgRgb);
  const l2 = relativeLuminance(bgRgb);
  const lighter = Math.max(l1, l2);
  const darker = Math.min(l1, l2);
  return (lighter + 0.05) / (darker + 0.05);
}

export function auditTheme(
  tokens: ThemeTokens,
  kind: ThemeKind,
): ThemeAuditResult {
  const missingTokens: string[] = [];
  const contrastWarnings: string[] = [];
  for (const [target] of CORE_TOKEN_MAP) {
    const value = tokens[target];
    if (value === undefined || value === null || value.trim() === "") {
      missingTokens.push(target);
    }
  }
  const fg = tokens["--color-foreground"];
  const bg = tokens["--color-background"];
  if (fg && bg && fg.trim() !== "" && bg.trim() !== "") {
    const ratio = contrastRatio(fg, bg);
    if (ratio === null) {
      contrastWarnings.push("unparseable fg/bg: " + JSON.stringify({ fg, bg }));
    } else if (ratio < 4.5) {
      contrastWarnings.push(
        "fg/bg contrast " +
          ratio.toFixed(2) +
          ":1 below WCAG AA 4.5:1 (" +
          fg +
          " on " +
          bg +
          ")",
      );
    }
  }
  return { kind, missingTokens, contrastWarnings };
}
