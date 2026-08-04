// Loader for the curated golden-layouts library (#1833).
//
// Golden layouts are repo-versioned, ship-immutable layout blueprints
// (`golden_layouts/*.json`) — distinct from ephemeral user layouts stored
// in globalState (#1831). Each is validated through the shared
// `validateLayout()` gate and dropped (with a log) if it fails so a
// malformed golden layout never crashes activation.
//
// The loaded list is cached at module scope so repeated quick-pick opens
// don't re-hit disk. `resetCache()` is provided for tests.

import * as vscode from "vscode";
import { readFile, readdir } from "node:fs/promises";
import * as path from "node:path";
import type { Layout } from "../layouts/types";
import { validateLayout } from "../layouts/types";
import { getFixtureWidgetsManifest } from "../layouts/registry";

let _cache: GoldenLayout[] | null = null;

export function resetCache(): void {
  _cache = null;
}

export interface GoldenLayout extends Layout {
  sourceGoldenId: string;
}

export async function loadGoldenLayouts(
  context: Pick<vscode.ExtensionContext, "extensionUri" | "extensionPath">,
  log?: (msg: string) => void,
): Promise<GoldenLayout[]> {
  if (_cache) {
    return _cache;
  }

  const dir = path.join(context.extensionPath, "golden_layouts");
  const widgetIds = new Set(
    (await getFixtureWidgetsManifest(context)).map((w) => w.id),
  );

  let files: string[] = [];
  try {
    files = (await readdir(dir)).filter((f) => f.endsWith(".json")).sort();
  } catch (err) {
    log?.(`[golden] failed to read ${dir}: ${String(err)}`);
    _cache = [];
    return _cache;
  }

  const out: GoldenLayout[] = [];
  for (const f of files) {
    const full = path.join(dir, f);
    let parsed: Layout;
    try {
      parsed = JSON.parse(await readFile(full, "utf-8")) as Layout;
    } catch (err) {
      log?.(`[golden] skip ${f}: parse error ${String(err)}`);
      continue;
    }
    const errs = validateLayout(parsed, widgetIds);
    if (errs.length > 0) {
      log?.(`[golden] skip ${f}: ${errs.join("; ")}`);
      continue;
    }
    out.push({ ...parsed, sourceGoldenId: parsed.id });
  }

  _cache = out;
  return out;
}
