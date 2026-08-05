// User-defined layout CRUD + workspace export/import (#1831).
//
// Persists user layouts in globalState under key `openbb.userLayouts`.
// Workspace layouts live in `.openbb/layouts/*.json` and are read on
// demand. Builtin layouts come from the injected getBuiltinLayouts.

import * as vscode from "vscode";
import type { Layout } from "./types";
import { validateLayout } from "./types";

const STORAGE_KEY = "openbb.userLayouts";

export interface LayoutManagerConfig {
  getBuiltinLayouts: () => Promise<Layout[]>;
  workspaceRoot?: string;
  fs?: Pick<vscode.FileSystem, "readFile" | "writeFile" | "createDirectory" | "stat">;
}

type StoredLayout = Layout & { schemaVersion: number };

export function toSlug(s: string): string {
  return s.toLowerCase().replace(/[^a-z0-9-]+/g, "-").replace(/^-+|-+$/g, "");
}

function freshId(existing: Set<string>, base: string): string {
  const slug = toSlug(base) || "layout";
  let candidate = slug;
  let n = 1;
  while (existing.has(candidate)) {
    n += 1;
    candidate = `${slug}-${n}`;
  }
  return candidate;
}

export class LayoutManager {
  private readonly context: vscode.ExtensionContext;
  private readonly cfg: LayoutManagerConfig;
  private readonly fs: Pick<vscode.FileSystem, "readFile" | "writeFile" | "createDirectory" | "stat">;

  constructor(context: vscode.ExtensionContext, config: LayoutManagerConfig) {
    this.context = context;
    this.cfg = config;
    this.fs = config.fs ?? vscode.workspace.fs;
  }

  private readUser(): Record<string, StoredLayout> {
    const raw = this.context.globalState.get<Record<string, StoredLayout>>(STORAGE_KEY);
    return raw ? { ...raw } : {};
  }

  private async writeUser(map: Record<string, StoredLayout>): Promise<void> {
    await this.context.globalState.update(STORAGE_KEY, map);
  }

  private async readWorkspaceLayouts(): Promise<Layout[]> {
    if (!this.cfg.workspaceRoot) {
      return [];
    }
    const dir = vscode.Uri.joinPath(vscode.Uri.file(this.cfg.workspaceRoot), ".openbb", "layouts");
    try {
      await this.fs.stat(dir);
    } catch {
      return [];
    }
    const out: Layout[] = [];
    try {
      const entries = await vscode.workspace.fs.readDirectory(dir);
      for (const [name, kind] of entries) {
        if (kind !== vscode.FileType.File || !name.endsWith(".json")) {
          continue;
        }
        try {
          const bytes = await this.fs.readFile(vscode.Uri.joinPath(dir, name));
          const parsed = JSON.parse(Buffer.from(bytes).toString("utf-8")) as Layout;
          out.push(parsed);
        } catch {
          // skip malformed
        }
      }
    } catch {
      // readDirectory failed; treat as empty
    }
    return out;
  }

  async listAll(): Promise<{ builtins: Layout[]; user: Layout[]; workspace: Layout[] }> {
    const builtins = await this.cfg.getBuiltinLayouts();
    const userMap = this.readUser();
    const user = Object.values(userMap);
    const workspace = await this.readWorkspaceLayouts();
    return { builtins, user, workspace };
  }

  async createLayout(name: string, templateId?: string): Promise<Layout> {
    const userMap = this.readUser();
    const builtinIds = new Set<string>();
    let template: Layout | undefined;
    if (templateId !== undefined) {
      const builtins = await this.cfg.getBuiltinLayouts();
      for (const b of builtins) {
        builtinIds.add(b.id);
      }
      template = builtins.find((b) => b.id === templateId);
      if (!template) {
        throw new Error(`template not found: ${templateId}`);
      }
    }
    const taken = new Set<string>([...Object.keys(userMap), ...builtinIds]);
    const id = freshId(taken, name);
    const layout: StoredLayout = template
      ? {
          id,
          name,
          gridTemplate: template.gridTemplate,
          slots: template.slots.map((s) => ({ ...s })),
          schemaVersion: 1,
        }
      : { id, name, gridTemplate: "12-col", slots: [], schemaVersion: 1 };
    userMap[id] = layout;
    await this.writeUser(userMap);
    return layout;
  }

  async renameLayout(id: string, newName: string): Promise<void> {
    const userMap = this.readUser();
    if (!userMap[id]) {
      throw new Error(`user layout not found: ${id}`);
    }
    userMap[id] = { ...userMap[id], name: newName };
    await this.writeUser(userMap);
  }

  async duplicateLayout(id: string): Promise<Layout> {
    const userMap = this.readUser();
    const builtins = await this.cfg.getBuiltinLayouts();
    const source = userMap[id] ?? builtins.find((b) => b.id === id);
    if (!source) {
      throw new Error(`layout not found: ${id}`);
    }
    const taken = new Set<string>([...Object.keys(userMap), ...builtins.map((b) => b.id)]);
    const newName = `${source.name} (copy)`;
    const newId = freshId(taken, newName);
    const copy: StoredLayout = {
      id: newId,
      name: newName,
      gridTemplate: source.gridTemplate,
      slots: source.slots.map((s) => ({ ...s })),
      schemaVersion: 1,
    };
    userMap[newId] = copy;
    await this.writeUser(userMap);
    return copy;
  }

  async deleteLayout(id: string): Promise<void> {
    const builtins = await this.cfg.getBuiltinLayouts();
    if (builtins.some((b) => b.id === id)) {
      throw new Error(`cannot delete builtin layout: ${id}`);
    }
    const userMap = this.readUser();
    if (!userMap[id]) {
      throw new Error(`user layout not found: ${id}`);
    }
    delete userMap[id];
    await this.writeUser(userMap);
  }

  async exportToWorkspace(id: string): Promise<vscode.Uri> {
    if (!this.cfg.workspaceRoot) {
      throw new Error("no workspace root — open a folder first");
    }
    const userMap = this.readUser();
    const builtins = await this.cfg.getBuiltinLayouts();
    const layout = userMap[id] ?? builtins.find((b) => b.id === id);
    if (!layout) {
      throw new Error(`layout not found: ${id}`);
    }
    const rootUri = vscode.Uri.file(this.cfg.workspaceRoot);
    const dir = vscode.Uri.joinPath(rootUri, ".openbb", "layouts");
    await this.fs.createDirectory(dir);
    const slug = toSlug(id);
    const target = vscode.Uri.joinPath(dir, `${slug}.json`);
    const payload: StoredLayout = {
      id: layout.id,
      name: layout.name,
      gridTemplate: layout.gridTemplate,
      slots: layout.slots,
      schemaVersion: 1,
    };
    const bytes = Buffer.from(JSON.stringify(payload, null, 2) + "\n", "utf-8");
    await this.fs.writeFile(target, bytes);
    return target;
  }

  async importFromFile(uri: vscode.Uri): Promise<Layout> {
    const bytes = await this.fs.readFile(uri);
    const parsed = JSON.parse(Buffer.from(bytes).toString("utf-8")) as Layout;
    const knownIds = new Set<string>(parsed.slots.map((s) => s.widgetId));
    const errors = validateLayout(parsed, knownIds);
    if (errors.length > 0) {
      throw new Error(`invalid layout: ${errors.join("; ")}`);
    }
    const userMap = this.readUser();
    const builtins = await this.cfg.getBuiltinLayouts();
    const taken = new Set<string>([...Object.keys(userMap), ...builtins.map((b) => b.id)]);
    const id = freshId(taken, parsed.id || parsed.name || "imported");
    const stored: StoredLayout = {
      id,
      name: parsed.name,
      gridTemplate: parsed.gridTemplate,
      slots: parsed.slots.map((s) => ({ ...s })),
      schemaVersion: 1,
    };
    userMap[id] = stored;
    await this.writeUser(userMap);
    return stored;
  }
}
