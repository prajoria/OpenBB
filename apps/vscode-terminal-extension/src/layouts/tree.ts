// Layouts sidebar tree view (#1831).

import * as vscode from "vscode";
import type { Layout } from "./types";
import type { LayoutManager } from "./manager";

type Bucket = "builtin" | "user" | "workspace";

export interface LayoutNode {
  kind: "group" | "layout";
  bucket: Bucket;
  layout?: Layout;
  label: string;
}

export class LayoutsTreeProvider implements vscode.TreeDataProvider<LayoutNode> {
  private readonly _onDidChangeTreeData = new vscode.EventEmitter<
    LayoutNode | undefined | void
  >();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(private readonly manager: LayoutManager) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(element: LayoutNode): vscode.TreeItem {
    if (element.kind === "group") {
      const item = new vscode.TreeItem(
        element.label,
        vscode.TreeItemCollapsibleState.Expanded,
      );
      item.contextValue = `openbbLayoutGroup:${element.bucket}`;
      return item;
    }
    const item = new vscode.TreeItem(
      element.label,
      vscode.TreeItemCollapsibleState.None,
    );
    item.contextValue =
      element.bucket === "builtin"
        ? "openbbBuiltinLayout"
        : "openbbLayout";
    item.tooltip = element.layout?.id ?? "";
    return item;
  }

  async getChildren(element?: LayoutNode): Promise<LayoutNode[]> {
    if (!element) {
      return [
        { kind: "group", bucket: "builtin", label: "Built-in" },
        { kind: "group", bucket: "user", label: "User" },
        { kind: "group", bucket: "workspace", label: "Workspace" },
      ];
    }
    if (element.kind !== "group") {
      return [];
    }
    const buckets = await this.manager.listAll();
    const list =
      element.bucket === "builtin"
        ? buckets.builtins
        : element.bucket === "user"
          ? buckets.user
          : buckets.workspace;
    return list.map((layout) => ({
      kind: "layout" as const,
      bucket: element.bucket,
      layout,
      label: layout.name,
    }));
  }
}

export function registerLayoutsTree(
  context: vscode.ExtensionContext,
  layoutManager: LayoutManager,
): vscode.Disposable {
  const provider = new LayoutsTreeProvider(layoutManager);
  const disposable = vscode.window.registerTreeDataProvider(
    "openbbLayouts",
    provider,
  );
  context.subscriptions.push(disposable);
  return disposable;
}
