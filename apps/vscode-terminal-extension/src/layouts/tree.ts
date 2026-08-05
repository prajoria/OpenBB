// Layouts sidebar tree provider (#1831).

import * as vscode from "vscode";
import type { LayoutManager } from "./manager";
import type { Layout } from "./types";

type SectionKey = "builtins" | "user" | "workspace";

interface SectionNode {
  kind: "section";
  key: SectionKey;
  label: string;
}

interface LayoutNode {
  kind: "layout";
  layout: Layout;
  section: SectionKey;
}

type TreeNode = SectionNode | LayoutNode;

export class LayoutsTreeProvider implements vscode.TreeDataProvider<TreeNode> {
  private readonly _emitter = new vscode.EventEmitter<TreeNode | undefined>();
  readonly onDidChangeTreeData = this._emitter.event;

  constructor(private readonly manager: LayoutManager) {}

  refresh(): void {
    this._emitter.fire(undefined);
  }

  getTreeItem(element: TreeNode): vscode.TreeItem {
    if (element.kind === "section") {
      const item = new vscode.TreeItem(
        element.label,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.iconPath = new vscode.ThemeIcon("layout");
      item.contextValue = "openbbLayoutSection";
      return item;
    }
    const item = new vscode.TreeItem(
      element.layout.name,
      vscode.TreeItemCollapsibleState.None,
    );
    item.iconPath = new vscode.ThemeIcon("window");
    item.contextValue =
      element.section === "builtins" ? "openbbBuiltinLayout" : "openbbLayout";
    item.tooltip = `${element.layout.id} (${element.layout.slots.length} widgets)`;
    return item;
  }

  async getChildren(element?: TreeNode): Promise<TreeNode[]> {
    if (!element) {
      return [
        { kind: "section", key: "builtins", label: "Built-in" },
        { kind: "section", key: "user", label: "User" },
        { kind: "section", key: "workspace", label: "Workspace" },
      ];
    }
    if (element.kind === "layout") {
      return [];
    }
    const all = await this.manager.listAll();
    const src =
      element.key === "builtins"
        ? all.builtins
        : element.key === "user"
          ? all.user
          : all.workspace;
    return src.map((l) => ({ kind: "layout", layout: l, section: element.key }));
  }
}

export function registerLayoutsTree(
  context: vscode.ExtensionContext,
  layoutManager: LayoutManager,
): { disposable: vscode.Disposable; refresh(): void } {
  const provider = new LayoutsTreeProvider(layoutManager);
  const view = vscode.window.registerTreeDataProvider("openbbLayouts", provider);
  context.subscriptions.push(view);
  return { disposable: view, refresh: () => provider.refresh() };
}
