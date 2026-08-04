// Pure types + validation. No vscode dependency so tests can import freely.

export type WidgetType = "table" | "chart" | "markdown" | "metric" | "note";

export interface WidgetMeta {
  id: string;
  name: string;
  type: WidgetType | string;
  endpoint: string;
  category: string;
  fixtureRows?: unknown;
}

export interface WidgetSlot {
  widgetId: string;
  col: number;
  span: number;
  row?: number;
}

export interface Layout {
  id: string;
  name: string;
  gridTemplate: string;
  slots: WidgetSlot[];
  schemaVersion?: number;
}

export function validateLayout(layout: Layout, knownWidgetIds?: Set<string>): string[] {
  const errors: string[] = [];
  if (!layout.id || !layout.name || !Array.isArray(layout.slots)) {
    errors.push(`layout missing required fields: ${layout.id ?? "<unknown>"}`);
    return errors;
  }
  const rows = new Map<number, Array<{ start: number; end: number }>>();
  for (const slot of layout.slots) {
    if (!slot.widgetId || typeof slot.col !== "number" || typeof slot.span !== "number") {
      errors.push(`slot missing widgetId/col/span in ${layout.id}`);
      continue;
    }
    if (knownWidgetIds && !knownWidgetIds.has(slot.widgetId)) {
      errors.push(`unknown widgetId '${slot.widgetId}' in ${layout.id}`);
    }
    const end = slot.col + slot.span - 1;
    if (slot.col < 1 || end > 12) {
      errors.push(`slot ${slot.widgetId} exceeds 12-col grid (col=${slot.col}, span=${slot.span})`);
    }
    const row = slot.row ?? 1;
    const arr = rows.get(row) ?? [];
    for (const r of arr) {
      if (!(end < r.start || slot.col > r.end)) {
        errors.push(`slot overlap in ${layout.id} row ${row}: ${slot.widgetId}`);
      }
    }
    arr.push({ start: slot.col, end });
    rows.set(row, arr);
  }
  return errors;
}
