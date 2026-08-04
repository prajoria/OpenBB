// Sparkline SVG builder (#1825) — raw SVG string for embedding in a
// hover MarkdownString via a data-URI. Handles empty / flat inputs
// without crashing. Trend color: green for up, red for down/flat-down.

const GREEN = "#4CAF50";
const RED = "#F44336";

/**
 * Build a compact sparkline SVG for a close-price series. Returns a
 * well-formed `<svg>…</svg>` string on any input including empty / flat.
 */
export function buildSparklineSvg(
  closes: readonly number[],
  width = 200,
  height = 40,
): string {
  const pad = 2;
  const w = Math.max(20, Math.floor(width));
  const h = Math.max(10, Math.floor(height));
  if (!closes || closes.length === 0) {
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"></svg>`;
  }
  const min = Math.min(...closes);
  const max = Math.max(...closes);
  const positive = closes[closes.length - 1] >= closes[0];
  const stroke = positive ? GREEN : RED;
  const range = max - min;
  if (range === 0 || closes.length === 1) {
    const y = (h / 2).toFixed(2);
    const x1 = pad;
    const x2 = w - pad;
    return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><line x1="${x1}" y1="${y}" x2="${x2}" y2="${y}" stroke="${stroke}" stroke-width="1.5" fill="none"/></svg>`;
  }
  const n = closes.length;
  const innerW = w - 2 * pad;
  const innerH = h - 2 * pad;
  const points: string[] = [];
  for (let i = 0; i < n; i++) {
    const x = pad + (i / (n - 1)) * innerW;
    const norm = (closes[i] - min) / range;
    const y = pad + (1 - norm) * innerH;
    points.push(`${x.toFixed(2)},${y.toFixed(2)}`);
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${w}" height="${h}" viewBox="0 0 ${w} ${h}"><polyline points="${points.join(" ")}" stroke="${stroke}" stroke-width="1.5" fill="none" stroke-linejoin="round" stroke-linecap="round"/></svg>`;
}
