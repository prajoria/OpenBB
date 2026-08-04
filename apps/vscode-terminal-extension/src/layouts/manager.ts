// LayoutManager (#1831) — CRUD + persistence for user-defined layouts.

import * as vscode from "vscode";
import { promises as fs } from "node:fs";
import * as path from "node:path";
import type { Layout, WidgetSlot } from "./types";
import { validateLayout } from "./types";

export const USER_LAYOUTS_KEY = "openbb.userLayouts";
export const SCHEMA_VERSION = 1;

export interface PersistedLayout extends Layout {
  schemaVersion: number;
}

export interface LayoutManagerConfig {
  getBuiltinLayouts: () => Promise<Layout[]>;
  workspaceRoot?: string;
}

export interface MementoLike {
  get<T>(key: string, defaultValue: T): T;
  update(key: string, value: unknown): Thenable<void>;
}

export interface ContextLike {
  globalState: MementoLike;
}

function slugify(name: string): string {
  return name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 64) || "layout";
}

function randomId(): string {
  return `user-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`;
}

function toPersisted(layout: Layout): PersistedLayout {
  return { schemaVersion: SCHEMA_VERSION, ...layout };
}

export class LayoutManager {
  private readonly context: ContextLike;
  private readonly config: LayoutManagerConfig;

  constructor(context: ContextLike, config: LayoutManagerConfig) {
    this.context = context;
    this.config = config;
  }

  private readUserMap(): Record<string, PersistedLayout> {
    return this.context.globalState.get<Record<string, PersistedLayout>>(
      USER_LAYOUTS_KEY,
      {},
    );
  }

  private async writeUserMap(map: Record<string, PersistedLayout>): Promise<void> {
    await this.context.globalState.update(USER_LAYOUTS_KEY, map);
  }

  private workspaceLayoutsDir(): string | undefined {
    return this.config.workspaceRoot
      ? path.join(this.config.workspaceRoot, ".openbb", "layouts")
      : undefined;
  }

  private async readWorkspaceLayouts(): Promise<PersistedLayout[]> {
    const dir = this.workspaceLayoutsDir();
    if (!dir) {
      return [];
    }
    let entries: string[];
    try {
      entries = await fs.readdir(dir);
    } catch {
      return [];
    }
    const out: PersistedLayout[] = [];
    for (const name of entries) {
      if (!name.endsWith(".json")) {
        continue;
      }
      try {
        const raw = await fs.readFile(path.join(dir, name), "utf-8");
        const parsed = JSON.parse(raw) as PersistedLayout;
        if (parsed && typeof parsed.id === "string") {
          out.push(parsed);
        }
      } catch {
        // ignore malformed files
      }
    }
    return out;
  }

  async listAll(): Promise<{
    builtins: Layout[];
    user: Layout[];
    workspace: Layout[];
  }> {
    const builtins = await this.config.getBuiltinLayouts();
    const userMap = this.readUserMap();
    const user = Object.values(userMap);
    const workspaceAll = await this.readWorkspaceLayouts();
    const seen = new Set<string>([
      ...builtins.map((l) => l.id),
      ...user.map((l) => l.id),
    ]);
    const workspace: PersistedLayout[] = [];
    for (const l of workspaceAll) {
      if (!seen.has(l.id)) {
        seen.add(l.id);
        workspace.push(l);
      }
    }
    return { builtins, user, workspace };
  }

  async createLayout(name: string, templateId?: string): Promise<PersistedLayout> {
    let slots: WidgetSlot[] = [];
    let gridTemplate = "12-col";
    if (templateId) {
      const builtins = await this.config.getBuiltinLayouts();
      const tmpl = builtins.find((b) => b.id === templateId);
      if (tmpl) {
        slots = tmpl.slots.map((s) => ({ ...s }));
        gridTemplate = tmpl.gridTemplate;
      }
    }
    const layout: PersistedLayout = {
      schemaVersion: SCHEMA_VERSION,
      id: randomId(),
      name,
      gridTemplate,
      slots,
    };
    const map = this.readUserMap();
    map[layout.id] = layout;
    await this.writeUserMap(map);
    return layout;
  }

  async renameLayout(id: string, newName: string): Promise<void> {
    const map = this.readUserMap();
    const existing = map[id];
    if (!existing) {
      throw new Error(`layout not found: ${id}`);
    }
    existing.name = newName;
    map[id] = existing;
    await this.writeUserMap(map);
  }

  async duplicateLayout(id: string): Promise<PersistedLayout> {
    const map = this.readUserMap();
    const src = map[id];
    let source: Layout | undefined = src;
    if (!source) {
      const builtins = await this.config.getBuiltinLayouts();
      source = builtins.find((b) => b.id === id);
    }
    if (!source) {
      throw new Error(`layout not found: ${id}`);
    }
    const copy: PersistedLayout = {
      schemaVersion: SCHEMA_VERSION,
      id: randomId(),
      name: `${source.name} (copy)`,
      gridTemplate: source.gridTemplate,
      slots: source.slots.map((s) => ({ ...s })),
    };
    map[copy.id] = copy;
    await this.writeUserMap(map);
    return copy;
  }

  async deleteLayout(id: string): Promise<void> {
    const builtins = await this.config.getBuiltinLayouts();
    if (builtins.some((b) => b.id === id)) {
      throw new Error(`cannot delete built-in layout: ${id}`);
    }
    const map = this.readUserMap();
    if (!map[id]) {
      throw new Error(`layout not found: ${id}`);
    }
    delete map[id];
    await this.writeUserMap(map);
  }

  async exportToWorkspace(id: string): Promise<vscode.Uri> {
    const dir = this.workspaceLayoutsDir();
    if (!dir) {
      throw new Error("no workspace folder open");
    }
    const map = this.readUserMap();
    const layout = map[id];
    if (!layout) {
      throw new Error(`layout not found: ${id}`);
    }
    await fs.mkdir(dir, { recursive: true });
    const target = path.join(dir, `${slugify(layout.name)}.json`);
    await fs.writeFile(target, JSON.stringify(toPersisted(layout), null, 2), "utf-8");
    return vscode.Uri.file(target);
  }

  async importFromFile(uri: vscode.Uri): Promise<PersistedLayout> {
    const raw = await fs.readFile(uri.fsPath, "utf-8");
    const parsed = JSON.parse(raw) as PersistedLayout;
    if (!parsed || typeof parsed.id !== "string" || typeof parsed.name !== "string") {
      throw new Error("invalid layout file: missing id/name");
    }
    const knownIds = new Set<string>((parsed.slots ?? []).map((s) => s.widgetId));
    const errs = validateLayout(parsed, knownIds).filter(
      (e) => !e.startsWith("unknown widgetId"),
    );
    if (errs.length > 0) {
      throw new Error(`invalid layout: ${errs.join("; ")}`);
    }
    const map = this.readUserMap();
    const imported: PersistedLayout = {
      schemaVersion: SCHEMA_VERSION,
      id: map[parsed.id] ? randomId() : parsed.id,
      name: parsed.name,
      gridTemplate: parsed.gridTemplate ?? "12-col",
      slots: parsed.slots.map((s) => ({ ...s })),
    };
    map[imported.id] = imported;
    await this.writeUserMap(map);
    return imported;
  }
}
