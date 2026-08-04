import * as vscode from "vscode";
import { readFile } from "node:fs/promises";
import type { Layout, WidgetMeta } from "./types";

export type { Layout, WidgetMeta, WidgetSlot, WidgetType } from "./types";
export { validateLayout } from "./types";

interface WidgetsManifestFile {
  version?: string;
  widgets: WidgetMeta[];
}

async function readJson<T>(uri: vscode.Uri): Promise<T> {
  const buf = await readFile(uri.fsPath, "utf-8");
  return JSON.parse(buf) as T;
}

export async function getBuiltinLayouts(
  context: Pick<vscode.ExtensionContext, "extensionUri">
): Promise<Layout[]> {
  const base = vscode.Uri.joinPath(context.extensionUri, "fixtures", "layouts");
  const files = ["portfolio-overview.json", "equity-deep-dive.json"];
  const layouts: Layout[] = [];
  for (const f of files) {
    layouts.push(await readJson<Layout>(vscode.Uri.joinPath(base, f)));
  }
  return layouts;
}

export async function getFixtureWidgetsManifest(
  context: Pick<vscode.ExtensionContext, "extensionUri">
): Promise<WidgetMeta[]> {
  const uri = vscode.Uri.joinPath(context.extensionUri, "fixtures", "widgets.sample.json");
  const parsed = await readJson<WidgetsManifestFile>(uri);
  return parsed.widgets;
}
