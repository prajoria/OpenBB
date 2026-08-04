// Golden-layouts commands (#1833).
//
// - openbb.loadGoldenLayout: quick-pick over the curated collection;
//   the picked layout is deep-copied into globalState `openbb.userLayouts`
//   with a freshly-minted id and preserved `sourceGoldenId` so it can be
//   edited without mutating the shipped blueprint.
// - openbb.resetToDefaultLayouts: modal confirm, then clear the
//   `openbb.userLayouts` key.

import * as vscode from "vscode";
import type { Layout } from "../layouts/types";
import { loadGoldenLayouts, type GoldenLayout } from "./loader";

const USER_LAYOUTS_KEY = "openbb.userLayouts";

interface StoredLayout extends Layout {
  sourceGoldenId?: string;
}

function newLayoutId(base: string): string {
  const suffix = Math.random().toString(36).slice(2, 8);
  const ts = Date.now().toString(36);
  return `user-${base}-${ts}-${suffix}`;
}

async function loadGoldenAndPick(
  context: vscode.ExtensionContext,
  log: (msg: string) => void,
): Promise<GoldenLayout | undefined> {
  const layouts = await loadGoldenLayouts(context, log);
  if (layouts.length === 0) {
    void vscode.window.showWarningMessage(
      "OpenBB: no golden layouts available.",
    );
    return undefined;
  }
  const pick = await vscode.window.showQuickPick(
    layouts.map((l) => ({
      label: l.name,
      description: l.id,
      layout: l,
    })),
    { placeHolder: "Select a golden layout to load" },
  );
  return pick?.layout;
}

export function registerGoldenCommands(
  context: vscode.ExtensionContext,
  outputChannel?: vscode.OutputChannel,
): void {
  const log = (msg: string): void => {
    outputChannel?.appendLine(msg);
  };

  context.subscriptions.push(
    vscode.commands.registerCommand("openbb.loadGoldenLayout", async () => {
      const picked = await loadGoldenAndPick(context, log);
      if (!picked) {
        return;
      }
      const existing = context.globalState.get<StoredLayout[]>(
        USER_LAYOUTS_KEY,
        [],
      );
      const copy: StoredLayout = {
        ...(JSON.parse(JSON.stringify(picked)) as Layout),
        id: newLayoutId(picked.id),
        sourceGoldenId: picked.sourceGoldenId ?? picked.id,
      };
      await context.globalState.update(USER_LAYOUTS_KEY, [...existing, copy]);
      void vscode.window.showInformationMessage(
        `Loaded golden layout: ${picked.name}`,
      );
    }),
    vscode.commands.registerCommand(
      "openbb.resetToDefaultLayouts",
      async () => {
        const confirm = await vscode.window.showWarningMessage(
          "Clear all user layouts and reset to defaults?",
          { modal: true },
          "Reset",
        );
        if (confirm !== "Reset") {
          return;
        }
        await context.globalState.update(USER_LAYOUTS_KEY, undefined);
        void vscode.window.showInformationMessage(
          "OpenBB: user layouts cleared.",
        );
      },
    ),
  );
}
