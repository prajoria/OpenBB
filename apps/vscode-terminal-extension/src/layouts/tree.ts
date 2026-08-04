import * as vscode from "vscode";
import type { LayoutManager } from "./manager";
import type { Layout } from "./types";

type Section = "builtins" | "user" | "workspace";

export class LayoutTreeItem extends vscode.TreeItem {
  constructor(
    public readonly layout: Layout,
    public readonly section: Section,
  ) {
    super(layout.name, vscode.TreeItemCollapsibleState.None);
    this.id = `${section}:${layout.id}`;
    this.tooltip = `${layout.name} (${layout.slots.length} slots)`;
    this.description = layout.id;
    this.contextValue =
      section === "builtins" ? "openbbBuiltinLayout" : "openbbLayout";
  }
}

class SectionItem extends vscode.TreeItem {
  constructor(label: string, public readonly section: Section) {
    super(label, vscode.TreeItemCollapsibleState.Expanded);
    this.contextValue = "openbbLayoutSection";
  }
}

export class LayoutsTreeProvider
  implements vscode.TreeDataProvider<vscode.TreeItem>
{
  private readonly _onDidChange = new vscode.EventEmitter<
    vscode.TreeItem | undefined | null | void
  >();
  readonly onDidChangeTreeData = this._onDidChange.event;

  constructor(private readonly manager: LayoutManager) {}

  refresh(): void {
    this._onDidChange.fire();
  }

  getTreeItem(element: vscode.TreeItem): vscode.TreeItem {
    return element;
  }

  async getChildren(element?: vscode.TreeItem): Promise<vscode.TreeItem[]> {
    if (!element) {
      return [
        new SectionItem("Built-in", "builtins"),
        new SectionItem("User", "user"),
        new SectionItem("Workspace", "workspace"),
      ];
    }
    if (element instanceof SectionItem) {
      const all = await this.manager.listAll();
      const bucket = all[element.section];
      return bucket.map((l) => new LayoutTreeItem(l, element.section));
    }
    return [];
  }
}
