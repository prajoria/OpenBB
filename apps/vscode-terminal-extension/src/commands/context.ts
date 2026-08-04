// Focus-context helper (#1822).
//
// Binds `openbb.terminalFocused` to the panel's active state so that
// keybindings scoped `when: openbb.terminalFocused` fire only while
// the OpenBB webview panel is in focus.

import * as vscodeReal from "vscode";

export interface FocusVsCodeApi {
  commands: {
    executeCommand(cmd: string, ...args: unknown[]): Thenable<unknown>;
  };
}

export interface FocusablePanel {
  onDidChangeViewState(
    listener: (e: { webviewPanel: { active: boolean } }) => void,
  ): { dispose(): void };
  onDidDispose(listener: () => void): { dispose(): void };
  active: boolean;
}

export function registerPanelFocusContext(
  panel: FocusablePanel,
  vscodeApi: FocusVsCodeApi = vscodeReal as unknown as FocusVsCodeApi,
): { dispose(): void } {
  const set = (v: boolean): void => {
    void vscodeApi.commands.executeCommand(
      "setContext",
      "openbb.terminalFocused",
      v,
    );
  };
  set(panel.active);
  const stateSub = panel.onDidChangeViewState((e) => {
    set(e.webviewPanel.active);
  });
  const disposeSub = panel.onDidDispose(() => {
    set(false);
  });
  return {
    dispose(): void {
      stateSub.dispose();
      disposeSub.dispose();
    },
  };
}
