// Widget Browser tree-view (#1830).
//
// Groups widgets from the fixture manifest by identifier prefix
// (pi_/tt_/portfolio_/regime_/other), sorts alpha within each group,
// and publishes the drag MIME `application/vnd.code.tree.openbb-widget`
// so future layout-drop targets (#1831) can consume the drop payload.

import * as vscode from "vscode";
import type { WidgetMeta } from "../layouts/types";

export type WidgetBrowserNode =
  | { kind: "prefix"; prefix: string; count: number }
  | { kind: "widget"; meta: WidgetMeta };

const PREFIX_ORDER: readonly string[] = [
  "pi_",
  "tt_",
  "portfolio_",
  "regime_",
  "other",
];

const OPENBB_WIDGET_MIME = "application/vnd.code.tree.openbb-widget";

function classifyPrefix(id: string): string {
  for (const p of PREFIX_ORDER) {
    if (p !== "other" && id.startsWith(p)) {
      return p;
    }
  }
  return "other";
}

function iconForType(type: string): vscode.ThemeIcon {
  switch (type) {
    case "metric":
      return new vscode.ThemeIcon("symbol-property");
    case "chart":
      return new vscode.ThemeIcon("graph-line");
    case "table":
      return new vscode.ThemeIcon("list-tree");
    case "note":
    case "markdown":
      return new vscode.ThemeIcon("note");
    default:
      return new vscode.ThemeIcon("symbol-misc");
  }
}

export class WidgetBrowserTreeProvider
  implements vscode.TreeDataProvider<WidgetBrowserNode>
{
  private readonly _onDidChangeTreeData =
    new vscode.EventEmitter<WidgetBrowserNode | undefined | void>();
  readonly onDidChangeTreeData = this._onDidChangeTreeData.event;

  constructor(
    private readonly config: { getManifest: () => Promise<WidgetMeta[]> },
  ) {}

  refresh(): void {
    this._onDidChangeTreeData.fire();
  }

  getTreeItem(node: WidgetBrowserNode): vscode.TreeItem {
    if (node.kind === "prefix") {
      const item = new vscode.TreeItem(
        `${node.prefix}* (${node.count})`,
        vscode.TreeItemCollapsibleState.Collapsed,
      );
      item.iconPath = new vscode.ThemeIcon("folder");
      return item;
    }
    const item = new vscode.TreeItem(
      node.meta.name,
      vscode.TreeItemCollapsibleState.None,
    );
    item.description = node.meta.type;
    item.tooltip = node.meta.endpoint;
    item.contextValue = "openbbWidget";
    item.iconPath = iconForType(node.meta.type);
    return item;
  }

  async getChildren(
    element?: WidgetBrowserNode,
  ): Promise<WidgetBrowserNode[]> {
    const manifest = await this.config.getManifest();
    if (!element) {
      const counts = new Map<string, number>();
      for (const w of manifest) {
        const p = classifyPrefix(w.id);
        counts.set(p, (counts.get(p) ?? 0) + 1);
      }
      const out: WidgetBrowserNode[] = [];
      for (const prefix of PREFIX_ORDER) {
        const count = counts.get(prefix) ?? 0;
        if (count > 0) {
          out.push({ kind: "prefix", prefix, count });
        }
      }
      return out;
    }
    if (element.kind === "prefix") {
      const matches = manifest
        .filter((w) => classifyPrefix(w.id) === element.prefix)
        .sort((a, b) => a.id.localeCompare(b.id));
      return matches.map((meta) => ({ kind: "widget", meta }));
    }
    return [];
  }
}

class WidgetDragController
  implements vscode.TreeDragAndDropController<WidgetBrowserNode>
{
  readonly dropMimeTypes: readonly string[] = [];
  readonly dragMimeTypes: readonly string[] = [OPENBB_WIDGET_MIME];

  handleDrag(
    source: readonly WidgetBrowserNode[],
    dataTransfer: vscode.DataTransfer,
  ): void {
    const metas: WidgetMeta[] = [];
    for (const node of source) {
      if (node.kind === "widget") {
        metas.push(node.meta);
      }
    }
    dataTransfer.set(
      OPENBB_WIDGET_MIME,
      new vscode.DataTransferItem(JSON.stringify(metas)),
    );
  }
}

export function registerWidgetBrowser(
  _context: vscode.ExtensionContext,
  getManifest: () => Promise<WidgetMeta[]>,
): { provider: WidgetBrowserTreeProvider; disposable: vscode.Disposable } {
  const provider = new WidgetBrowserTreeProvider({ getManifest });
  const dnd = new WidgetDragController();
  const treeView = vscode.window.createTreeView<WidgetBrowserNode>(
    "openbbWidgets",
    {
      treeDataProvider: provider,
      showCollapseAll: true,
      dragAndDropController: dnd,
    },
  );
  return { provider, disposable: treeView };
}
