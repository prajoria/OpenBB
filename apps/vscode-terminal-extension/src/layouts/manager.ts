// User-defined layouts CRUD + workspace export/import (#1831).

import * as vscode from "vscode";
import { randomUUID } from "node:crypto";
import { validateLayout } from "./types";
import type { Layout } from "./types";

const USER_LAYOUTS_KEY = "openbb.userLayouts";

export interface LayoutManagerConfig {
  getBuiltinLayouts: () => Promise<Layout[]>;
  workspaceRoot?: string;
}

export interface LayoutBuckets {
  builtins: Layout[];
  user: Layout[];
  workspace: Layout[];
}

function slugify(name: string): string {
  const s = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return s || "layout";
}

export class LayoutManager {
  private readonly context: vscode.ExtensionContext;
  private readonly config: LayoutManagerConfig;

  constructor(context: vscode.ExtensionContext, config: LayoutManagerConfig) {
    this.context = context;
    this.config = config;
  }

  private readUserLayouts(): Record<string, Layout> {
    return this.context.globalState.get<Record<string, Layout>>(
      USER_LAYOUTS_KEY,
      {},
    );
  }

  private async writeUserLayouts(
    map: Record<string, Layout>,
  ): Promise<void> {
    await this.context.globalState.update(USER_LAYOUTS_KEY, map);
  }

  async listAll(): Promise<LayoutBuckets> {
    const builtins = await this.config.getBuiltinLayouts();
    const user = Object.values(this.readUserLayouts());
    const workspace: Layout[] = [];
    if (this.config.workspaceRoot) {
      const dir = vscode.Uri.joinPath(
        vscode.Uri.file(this.config.workspaceRoot),
        ".openbb",
        "layouts",
      );
      try {
        const entries = await vscode.workspace.fs.readDirectory(dir);
        for (const [name, kind] of entries) {
          if (kind !== vscode.FileType.File || !name.endsWith(".json")) {
            continue;
          }
          try {
            const buf = await vscode.workspace.fs.readFile(
              vscode.Uri.joinPath(dir, name),
            );
            const text = new TextDecoder("utf-8").decode(buf);
            const parsed = JSON.parse(text) as Layout;
            workspace.push(parsed);
          } catch {
            // skip unreadable / invalid files
          }
        }
      } catch {
        // directory doesn't exist — leave workspace empty
      }
    }
    return { builtins, user, workspace };
  }

  async createLayout(name: string, templateId?: string): Promise<Layout> {
    const users = this.readUserLayouts();
    const id = randomUUID();
    let layout: Layout;
    if (templateId) {
      const builtins = await this.config.getBuiltinLayouts();
      const template = builtins.find((b) => b.id === templateId);
      if (!template) {
        throw new Error(`template not found: ${templateId}`);
      }
      layout = {
        id,
        name,
        gridTemplate: template.gridTemplate,
        schemaVersion: 1,
        slots: template.slots.map((s) => ({ ...s })),
      };
    } else {
      layout = {
        id,
        name,
        gridTemplate: "12-col",
        schemaVersion: 1,
        slots: [],
      };
    }
    users[id] = layout;
    await this.writeUserLayouts(users);
    return layout;
  }

  async renameLayout(id: string, newName: string): Promise<void> {
    const users = this.readUserLayouts();
    const existing = users[id];
    if (!existing) {
      throw new Error(`layout not found in user layouts: ${id}`);
    }
    users[id] = { ...existing, name: newName };
    await this.writeUserLayouts(users);
  }

  async duplicateLayout(id: string): Promise<Layout> {
    const users = this.readUserLayouts();
    const existing = users[id];
    if (!existing) {
      throw new Error(`layout not found in user layouts: ${id}`);
    }
    const newId = randomUUID();
    const copy: Layout = {
      ...existing,
      id: newId,
      name: `${existing.name} (copy)`,
      slots: existing.slots.map((s) => ({ ...s })),
    };
    users[newId] = copy;
    await this.writeUserLayouts(users);
    return copy;
  }

  async deleteLayout(id: string): Promise<void> {
    const builtins = await this.config.getBuiltinLayouts();
    if (builtins.some((b) => b.id === id)) {
      throw new Error(`cannot delete built-in layout: ${id}`);
    }
    const users = this.readUserLayouts();
    if (!(id in users)) {
      throw new Error(`layout not found in user layouts: ${id}`);
    }
    delete users[id];
    await this.writeUserLayouts(users);
  }

  async exportToWorkspace(id: string): Promise<vscode.Uri> {
    if (!this.config.workspaceRoot) {
      throw new Error("no workspace open — cannot export layout");
    }
    const users = this.readUserLayouts();
    const layout = users[id];
    if (!layout) {
      throw new Error(`layout not found in user layouts: ${id}`);
    }
    const dir = vscode.Uri.joinPath(
      vscode.Uri.file(this.config.workspaceRoot),
      ".openbb",
      "layouts",
    );
    await vscode.workspace.fs.createDirectory(dir);
    const uri = vscode.Uri.joinPath(dir, `${slugify(layout.name)}.json`);
    const data = new TextEncoder().encode(JSON.stringify(layout, null, 2));
    await vscode.workspace.fs.writeFile(uri, data);
    return uri;
  }

  async importFromFile(uri: vscode.Uri): Promise<Layout> {
    const buf = await vscode.workspace.fs.readFile(uri);
    const text = new TextDecoder("utf-8").decode(buf);
    const parsed = JSON.parse(text) as Layout;
    const errs = validateLayout(parsed);
    if (errs.length > 0) {
      throw new Error(`invalid layout: ${errs.join("; ")}`);
    }
    const users = this.readUserLayouts();
    const id =
      parsed.id && !(parsed.id in users) ? parsed.id : randomUUID();
    const layout: Layout = {
      ...parsed,
      id,
      schemaVersion: parsed.schemaVersion ?? 1,
    };
    users[id] = layout;
    await this.writeUserLayouts(users);
    return layout;
  }
}
